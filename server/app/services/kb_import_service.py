"""知识库批量导入服务：文件夹、多文件与 ZIP 压缩包。

为什么单独做一个服务文件：
    知识库原有的 upload_document 负责“一篇文档”的解析、图片匹配与切片，
    它已经被单篇上传验证过。批量导入不应该复制这套逻辑，而是负责
    “把一批文件拆成一个个单篇任务”，再复用同一条上传管道。
    这样两个入口的切片规则、图片规则、去重规则永远一致。

为什么复用 import_batches 与 ingestion_jobs，而不是新建两张表：
    这两张表本来就为“一次导入包含多个文件”设计，字段是通用的：
        import_batches  记录整批的状态与统计；
        ingestion_jobs  记录每个文件的状态、重试次数与失败原因。
    复用后，菜谱导入和知识库导入共用一套“批次 + 任务”模型，
    以后接入定时同步、失败重试、任务进程都不需要再改表结构。

处理流程：
    1. 接收多文件、相对路径列表（文件夹上传时由浏览器提供）与可选 ZIP；
    2. 安全解压与路径校验，按后缀分成文档、图片、忽略三类；
    3. 只保留“正文真正引用到”的图片，避免一批图片被每篇文档重复保存；
    4. 把原始文件暂存到对象存储，创建批次与每个文件一条任务；
    5. 返回批次后，后台任务逐个文件调用 upload_document 完成解析与切片；
    6. 失败的单个文件可以单独重试，不影响已经成功的文件。

为什么用 FastAPI 的后台任务，而不是同步处理：
    一个文件夹可能包含上百个文件，同步处理会让上传请求长时间不返回，
    浏览器和反向代理都会超时。后台任务先返回批次编号，前端轮询进度，
    体验和真实公司里的“异步导入”一致。
"""

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.serializers import iso
from app.core.errors import AppError
from app.core.security import new_id
from app.db.models import AdminUser, ImportBatch, IngestionJob
from app.db.rag_models import KbDocument
from app.services import kb_service
from app.services.audit_service import write_audit
from app.services.storage import get_storage
from app.utils.time import now_utc

# 来源类型与任务类型：写在常量里，查询历史批次时不用记字符串。
BATCH_SOURCE_TYPE = "kb_upload"
JOB_TYPE = "kb_ingest_document"
WORKER_NAME = "kb-import-background"

# 单个压缩包最大 50 MB。文档与图片单文件上限都是 5 MB，
# 50 MB 足够覆盖几百个文件的资料包，同时避免一次请求占用过多内存。
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
# 解压后总大小上限 100 MB。只限制压缩包大小不够：
# 压缩比极高的“压缩炸弹”解压后可能撑爆内存和磁盘。
MAX_UNPACKED_BYTES = 100 * 1024 * 1024
# 压缩包内条目上限（含目录）。防止几十万个小文件把处理时间拖到不可控。
MAX_ARCHIVE_ENTRIES = 1000
# 一个批次最多 200 篇文档、300 张图片，与现有列表分页上限保持一致。
MAX_BATCH_DOCUMENTS = 200
MAX_BATCH_IMAGES = 300

_DOCUMENT_SUFFIXES = kb_service.ALLOWED_SUFFIXES
_IMAGE_SUFFIXES = kb_service.ALLOWED_IMAGE_SUFFIXES
# Windows 路径可能带盘符（例如 C:/资料/a.md），在压缩包里属于非法绝对路径。
_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:")


@dataclass(eq=False)
class _Entry:
    """批量导入中的一个候选文件。

    path：压缩包内或文件夹内的相对路径，例如 `资料/菜谱/白灼虾.md`；
    data：文件原始字节；
    kind：document 文档、image 图片。被忽略的文件不会创建 _Entry。

    为什么不保存绝对路径：
        绝对路径既没有跨机器意义，也可能泄露上传者电脑的目录结构；
        相对路径已经足够用于“同目录图片优先匹配”和错误提示。
    """

    path: str
    data: bytes
    kind: str

    @property
    def filename(self) -> str:
        """只取文件名部分，用于存储键和 Markdown 图片匹配。"""
        return PurePosixPath(self.path).name


def _normalize_path(raw: str) -> str:
    """校验并规范化相对路径。

    作用：
        文件夹上传时浏览器会给出 `webkitRelativePath`，压缩包条目也会带路径。
        这些路径来自客户端，必须防御目录穿越：`../../etc/passwd` 这类路径
        一旦拼进存储键，就会把文件写到预期目录之外。
    拒绝规则：
        空路径、以 `/` 开头、带盘符、包含 `..` 段。
    为什么用 PurePosixPath：
        统一把反斜杠转成正斜杠后，用 POSIX 规则解析，Windows 和 Linux 行为一致。
    """
    text = (raw or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    if not text or text.startswith("/") or _DRIVE_LETTER_RE.match(text):
        raise AppError(
            "KB_IMPORT_PATH_INVALID",
            f"文件路径不合法：{raw}",
            status_code=400,
        )
    path = PurePosixPath(text)
    if any(part == ".." for part in path.parts):
        raise AppError(
            "KB_IMPORT_PATH_INVALID",
            f"文件路径不能包含上级目录：{raw}",
            status_code=400,
        )
    return str(path)


def _is_junk(path: str) -> bool:
    """判断是否是操作系统生成的垃圾文件。

    典型例子：macOS 压缩时会附带 `__MACOSX/` 目录，Windows 会生成 `.DS_Store`。
    这些文件不是知识内容，导入时直接跳过，避免它们占用任务和失败统计。
    """
    parts = PurePosixPath(path).parts
    if any(part.startswith("__MACOSX") for part in parts):
        return True
    return parts[-1].startswith(".")


def _classify(path: str) -> str:
    """按后缀把文件分成 document、image、ignored。

    只认白名单后缀：Markdown、纯文本、JPG、PNG、WebP。
    其他文件（PDF、Word、视频等）不报错但也不处理，计入“已忽略”，
    让运营知道压缩包里确实有文件没被导入。
    """
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in _DOCUMENT_SUFFIXES:
        return "document"
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    return "ignored"


def validate_archive_size(size: int | None) -> None:
    """在读取上传内容之前检查压缩包大小。

    作用：
        接口层能在 `UploadFile.size` 上提前看到大小，先拒绝超大文件，
        就不必把它整个读进内存。这是压缩包大小限制的第一道闸门，
        真正的解压后大小限制仍在 _read_archive 里完成。
    """
    if size and size > MAX_ARCHIVE_BYTES:
        raise AppError(
            "KB_ARCHIVE_TOO_LARGE", "压缩包不能超过 50 MB", status_code=413
        )


def _read_archive(filename: str, data: bytes) -> tuple[list[_Entry], int]:
    """安全读取 ZIP 压缩包，返回 (候选文件列表, 被忽略的文件数)。

    安全限制（面试常问“上传压缩包怎么防攻击”）：
    1. 压缩包本体不超过 50 MB；
    2. 解压后总大小不超过 100 MB，防止压缩炸弹；
    3. 条目数量不超过 1000；
    4. 拒绝加密压缩包与符号链接，避免读到预期之外的内容；
    5. 每个条目都做路径穿越校验；
    6. 读取时按单文件上限截断，不信任压缩包里声明的大小。

    为什么嵌套 ZIP 不递归解压：
        递归会让大小、层数、路径校验变得复杂，也容易被恶意构造的
        多层压缩包拖垮。需要导入嵌套压缩包时，让运营先手动解压更清晰。
    """
    if len(data) > MAX_ARCHIVE_BYTES:
        raise AppError(
            "KB_ARCHIVE_TOO_LARGE", "压缩包不能超过 50 MB", status_code=413
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise AppError(
            "KB_ARCHIVE_INVALID",
            f"{filename} 不是有效的 ZIP 压缩包",
            status_code=400,
        ) from exc

    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise AppError(
            "KB_ARCHIVE_TOO_MANY_FILES",
            f"压缩包内条目不能超过 {MAX_ARCHIVE_ENTRIES} 个",
            status_code=400,
        )

    entries: list[_Entry] = []
    ignored = 0
    unpacked = 0
    for info in infos:
        if info.is_dir():
            continue
        # flag_bits 最低位为 1 表示文件被加密，标准库无法读取。
        if info.flag_bits & 0x1:
            raise AppError(
                "KB_ARCHIVE_ENCRYPTED",
                "不支持加密压缩包，请解压后重新上传",
                status_code=400,
            )
        # external_attr 的高 16 位保存 Unix 文件权限，120000 表示符号链接。
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise AppError(
                "KB_ARCHIVE_SYMLINK",
                "压缩包内不允许包含符号链接",
                status_code=400,
            )

        path = _normalize_path(info.filename)
        unpacked += info.file_size
        if unpacked > MAX_UNPACKED_BYTES:
            raise AppError(
                "KB_ARCHIVE_TOO_LARGE",
                "压缩包解压后总大小不能超过 100 MB",
                status_code=413,
            )
        kind = _classify(path)
        if _is_junk(path) or kind == "ignored":
            ignored += 1
            continue

        limit = (
            kb_service.MAX_DOCUMENT_BYTES
            if kind == "document"
            else kb_service.MAX_KB_IMAGE_BYTES
        )
        if info.file_size > limit:
            raise AppError(
                "KB_FILE_TOO_LARGE",
                f"{PurePosixPath(path).name} 不能超过 5 MB",
                status_code=413,
            )
        try:
            with archive.open(info) as handle:
                # 多读 1 个字节：如果压缩包声明的大小不实，也能发现并拒绝。
                raw = handle.read(limit + 1)
        except (zipfile.BadZipFile, OSError) as exc:
            raise AppError(
                "KB_ARCHIVE_INVALID",
                "压缩包内容损坏，无法读取",
                status_code=400,
            ) from exc
        if len(raw) > limit:
            raise AppError(
                "KB_FILE_TOO_LARGE",
                f"{PurePosixPath(path).name} 不能超过 5 MB",
                status_code=413,
            )
        entries.append(_Entry(path=path, data=raw, kind=kind))
    return entries, ignored


def _decode_for_reference(data: bytes) -> str:
    """尝试按 UTF-8 解码正文，只用于提取图片引用。

    解码失败不在这里报错：真正的编码错误应该在处理该文件的任务里
    被记录成一条失败项，这样同一批其他文件仍然能成功导入。
    """
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return ""


def _pick_images(
    entry: _Entry, image_index: dict[str, list[_Entry]]
) -> list[_Entry]:
    """为一篇文档挑选它真正引用到的图片。

    匹配规则：
        1. 先从 Markdown 中提取本地图片文件名（与单篇上传使用同一规则）；
        2. 同名图片优先选文档所在目录的那一张；
        3. 同目录没有时，才使用其他目录里的同名图片；
        4. 同一张图片不会重复加入。

    为什么优先同目录：
        一个资料包里可能有多张 `步骤1.png`，同目录的那张才是这篇文章的配图。
        只在同目录找不到时才放宽到全局，兼顾准确性与兼容性。
    """
    text_content = _decode_for_reference(entry.data)
    doc_dir = PurePosixPath(entry.path).parent
    picked: list[_Entry] = []
    for name in kb_service.referenced_image_names(text_content):
        options = image_index.get(name) or []
        if not options:
            continue
        same_dir = [item for item in options if PurePosixPath(item.path).parent == doc_dir]
        chosen = sorted(same_dir or options, key=lambda item: item.path)[0]
        if chosen not in picked:
            picked.append(chosen)
    return picked


def _batch_label(
    label: str | None,
    archive_name: str | None,
    documents: list[_Entry],
) -> str:
    """给批次起一个可读名称，展示在批次列表与详情里。

    优先级：运营手填的名称 > 压缩包文件名 > 文件夹名 > “N 个文件”。
    这个名称只用于展示，不参与去重和匹配。
    """
    text = (label or "").strip()
    if text:
        return text[:255]
    if archive_name:
        return f"压缩包：{archive_name}"[:255]
    parents = {str(PurePosixPath(item.path).parent) for item in documents}
    if len(parents) == 1:
        parent = next(iter(parents))
        if parent != ".":
            return f"文件夹：{parent}"[:255]
    return f"{len(documents)} 个文件"


async def create_batch(
    db: AsyncSession,
    admin: AdminUser,
    *,
    label: str | None,
    files: list[tuple[str, bytes]],
    paths: list[str] | None,
    archive: tuple[str, bytes] | None,
    ip: str | None = None,
) -> dict[str, Any]:
    """创建一次批量导入：校验文件、暂存原始内容、生成任务。

    参数：
        files：普通多选或文件夹选择的文件，元素是 (文件名, 内容)；
        paths：与 files 一一对应的相对路径。文件夹上传时由浏览器提供，
               数量对不上时退回使用文件名，避免前端版本差异导致整批失败；
        archive：可选的 (压缩包文件名, 内容)。

    返回值：
        批次详情（含每个文件的任务状态），前端据此展示进度与失败清单。

    为什么先暂存再处理：
        后台任务在响应返回后才执行，此时请求里的文件对象已经关闭，
        必须把内容落到对象存储，任务才拿得到。暂存目录在批次结束后清理；
        有失败项时保留，供单独重试用。
    """
    entries: list[_Entry] = []
    ignored = 0
    archive_name: str | None = None

    if archive is not None:
        archive_name = kb_service.safe_filename(archive[0] or "archive.zip")
        if PurePosixPath(archive_name).suffix.lower() != ".zip":
            raise AppError(
                "KB_ARCHIVE_TYPE_UNSUPPORTED",
                "压缩包仅支持 ZIP 格式",
                status_code=400,
            )
        archive_entries, archive_ignored = _read_archive(archive_name, archive[1])
        entries.extend(archive_entries)
        ignored += archive_ignored

    normalized_paths = paths if paths and len(paths) == len(files) else None
    for index, (raw_name, raw_data) in enumerate(files):
        raw_path = normalized_paths[index] if normalized_paths else raw_name
        path = _normalize_path(raw_path)
        # 文件夹里如果混进了压缩包，这里不递归解压，只计入“已忽略”。
        kind = _classify(path)
        if _is_junk(path) or kind == "ignored":
            ignored += 1
            continue
        limit = (
            kb_service.MAX_DOCUMENT_BYTES
            if kind == "document"
            else kb_service.MAX_KB_IMAGE_BYTES
        )
        if not raw_data:
            raise AppError(
                "KB_FILE_EMPTY", f"{PurePosixPath(path).name} 内容为空", status_code=400
            )
        if len(raw_data) > limit:
            raise AppError(
                "KB_FILE_TOO_LARGE",
                f"{PurePosixPath(path).name} 不能超过 5 MB",
                status_code=413,
            )
        entries.append(_Entry(path=path, data=raw_data, kind=kind))

    documents = [entry for entry in entries if entry.kind == "document"]
    images = [entry for entry in entries if entry.kind == "image"]
    if not documents:
        raise AppError(
            "KB_IMPORT_EMPTY",
            "没有可解析的 .md 或 .txt 文件；图片需要和文档一起上传",
            status_code=400,
        )
    if len(documents) > MAX_BATCH_DOCUMENTS:
        raise AppError(
            "KB_IMPORT_TOO_MANY_DOCUMENTS",
            f"一个批次最多导入 {MAX_BATCH_DOCUMENTS} 篇文档",
            status_code=400,
        )
    if len(images) > MAX_BATCH_IMAGES:
        raise AppError(
            "KB_IMPORT_TOO_MANY_IMAGES",
            f"一个批次最多导入 {MAX_BATCH_IMAGES} 张图片",
            status_code=400,
        )
    total_bytes = sum(len(entry.data) for entry in entries)
    if total_bytes > MAX_UNPACKED_BYTES:
        raise AppError(
            "KB_IMPORT_TOO_LARGE",
            "本批文件总大小不能超过 100 MB",
            status_code=413,
        )

    # 图片在创建批次时就校验格式与真实类型：坏图片会拖垮所有引用它的文档，
    # 与其等后台任务逐个失败，不如在运营上传时立刻指出是哪一张。
    for entry in images:
        kb_service.validate_image(entry.filename, entry.data)

    image_index: dict[str, list[_Entry]] = {}
    for entry in images:
        image_index.setdefault(entry.filename.casefold(), []).append(entry)

    picked_by_doc: dict[str, list[_Entry]] = {
        entry.path: _pick_images(entry, image_index) for entry in documents
    }
    used_image_paths = {
        image.path for picked in picked_by_doc.values() for image in picked
    }
    # 未被任何文档引用的图片，不只记数量，还要记下“是哪个文件”。
    # 只给一个数字，运营看到“未被引用图片 3”时无从下手：不知道是哪三张、
    # 在哪个目录，也就无法判断是文档写错了文件名，还是图片本来就是多余素材。
    # 保存相对路径而不是纯文件名，是因为资料包里常有同名的 `步骤1.png`，
    # 只有路径才能唯一定位到具体文件。
    unused_image_paths = sorted(
        entry.path for entry in images if entry.path not in used_image_paths
    )

    batch_id = new_id("imp")
    staging_root = f"kb/imports/{batch_id}"
    storage = get_storage()

    # 图片只暂存一份，多个文档引用同一张图片时共用这个对象键。
    image_keys: dict[str, str] = {}
    for index, entry in enumerate(images):
        key = f"{staging_root}/images/{index:04d}_{kb_service.safe_filename(entry.filename)}"
        storage.put(key, entry.data)
        image_keys[entry.path] = key

    now = now_utc()
    batch = ImportBatch(
        id=batch_id,
        source_type=BATCH_SOURCE_TYPE,
        source_uri=_batch_label(label, archive_name, documents),
        source_ref=None,
        checksum=None,
        status="pending",
        stats={
            "total": len(documents),
            "pending": len(documents),
            "running": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "images": len(images),
            "ignored": ignored,
            "unusedImages": len(unused_image_paths),
            # 明细清单随批次保存，刷新页面或第二天再来看仍然查得到；
            # 暂存的图片文件在整批成功时会被删除，事后无法再从磁盘反推。
            "unusedImagePaths": unused_image_paths,
        },
        created_by=admin.id,
        created_at=now,
    )
    db.add(batch)

    jobs: list[IngestionJob] = []
    for index, entry in enumerate(documents):
        staged_key = f"{staging_root}/docs/{index:04d}_{kb_service.safe_filename(entry.filename)}"
        storage.put(staged_key, entry.data)
        picked = picked_by_doc[entry.path]
        job = IngestionJob(
            id=new_id("job"),
            batch_id=batch_id,
            job_type=JOB_TYPE,
            status="pending",
            attempts=0,
            payload={
                "relativePath": entry.path,
                "filename": entry.filename,
                "title": PurePosixPath(entry.path).stem[:120],
                "mime": (
                    "text/markdown"
                    if PurePosixPath(entry.path).suffix.lower() == ".md"
                    else "text/plain"
                ),
                "storageKey": staged_key,
                "images": [
                    {
                        "filename": image.filename,
                        "storageKey": image_keys[image.path],
                    }
                    for image in picked
                ],
            },
            result=None,
            error_message=None,
            run_after=now,
            created_at=now,
            updated_at=now,
        )
        db.add(job)
        jobs.append(job)

    write_audit(
        db,
        actor=admin,
        action="kb.import.create",
        target_type="import_batch",
        target_id=batch_id,
        after={
            "label": batch.source_uri,
            "documents": len(documents),
            "images": len(images),
            "ignored": ignored,
        },
        ip=ip,
    )
    await db.commit()
    return _batch_payload(batch, jobs)


def _staged_bytes(key: str | None) -> bytes:
    """读取暂存文件，缺失时给出可理解的错误。

    暂存文件只会被本服务清理，正常不会缺失；一旦缺失说明存储被外部改动，
    重试也无法恢复，因此提示运营重新创建批次。
    """
    if not key:
        raise AppError("KB_IMPORT_STAGED_MISSING", "暂存文件编号缺失，请重新创建批次")
    try:
        return get_storage().read(key)
    except FileNotFoundError as exc:
        raise AppError(
            "KB_IMPORT_STAGED_MISSING",
            "暂存文件已丢失，请重新创建批次",
            status_code=409,
        ) from exc


async def _actor_of(db: AsyncSession, batch: ImportBatch) -> AdminUser:
    """取批次发起人，供上传管道写入审计日志。

    管理员可能已被删除，但批次仍要能跑完；这时用一个只读的“系统导入”
    占位对象，保证审计日志里仍然有可追溯的操作者名称。
    """
    if batch.created_by:
        admin = await db.get(AdminUser, batch.created_by)
        if admin is not None:
            return admin
    return AdminUser(
        id=batch.created_by or "system",
        username="system",
        display_name="系统导入",
        password_hash="",
        status="active",
    )


async def _process_job(
    session_factory: async_sessionmaker[AsyncSession], job_id: str
) -> None:
    """处理一个文件任务：调用单篇上传管道，并把结果写回任务表。

    为什么每个任务使用独立会话：
        单篇处理可能失败并回滚。如果所有文件共用一个会话，
        一个文件回滚会连带丢掉其他文件尚未提交的数据。
        独立会话把失败影响严格限制在当前文件。

    去重策略：
        相同内容（SHA-256 一致）的文档在 upload_document 里会抛重复错误。
        批量导入把它记为 skipped 而不是 failed：重复不是错误，
        运营批量选择文件夹时很容易把同一份资料选两次。
    """
    async with session_factory() as db:
        # 先“抢占”任务：只有 pending 才能变成 running。
        # 这样即使同一批次被重复触发，也不会把同一个文件处理两次。
        claimed = await db.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id, IngestionJob.status == "pending")
            .values(
                status="running",
                attempts=IngestionJob.attempts + 1,
                locked_at=now_utc(),
                locked_by=WORKER_NAME,
            )
        )
        await db.commit()
        if claimed.rowcount == 0:
            return

        job = await db.get(IngestionJob, job_id)
        if job is None:
            return
        batch = await db.get(ImportBatch, job.batch_id)
        if batch is None:
            return
        actor = await _actor_of(db, batch)
        # 回滚会让 ORM 对象过期，先把后面要用到的值复制成普通字典。
        payload = dict(job.payload or {})
        previous = dict(job.result or {})
        batch_id = job.batch_id

        status = "succeeded"
        message: str | None = None
        result: dict[str, Any] = {}
        try:
            existing_id = previous.get("documentId")
            document = await db.get(KbDocument, existing_id) if existing_id else None
            if document is not None:
                # 上一次已经建过文档（例如切片失败）：只重新切片。
                # 直接重传会撞上内容去重，永远无法成功。
                document_payload, error = await kb_service.rechunk_document(
                    db, actor, document.id, None
                )
            else:
                images = [
                    (item.get("filename", "image.png"), _staged_bytes(item.get("storageKey")))
                    for item in payload.get("images", [])
                ]
                document_payload, error = await kb_service.upload_document(
                    db,
                    actor,
                    title=payload.get("title"),
                    filename=payload.get("filename", "document.md"),
                    mime=payload.get("mime"),
                    data=_staged_bytes(payload.get("storageKey")),
                    ip=None,
                    images=images,
                    source_type="batch_upload",
                    import_batch_id=batch_id,
                )
            result = {
                "documentId": document_payload.get("id"),
                "title": document_payload.get("title"),
                "chunkCount": document_payload.get("chunkCount", 0),
                "imageCount": document_payload.get("imageCount", 0),
                "unmatchedImageCount": document_payload.get("unmatchedImageCount", 0),
            }
            if error:
                status = "failed"
                message = error
        except AppError as exc:
            await db.rollback()
            if exc.code == "KB_DOCUMENT_DUPLICATE":
                status = "skipped"
                message = exc.message
            else:
                status = "failed"
                message = exc.message
        except Exception as exc:  # noqa: BLE001 - 单个文件的失败不能中断整批
            await db.rollback()
            status = "failed"
            message = kb_service.error_text(exc)

        job = await db.get(IngestionJob, job_id)
        if job is None:
            return
        job.status = status
        job.error_message = message[:500] if message else None
        job.result = result
        job.locked_at = None
        job.locked_by = None
        job.updated_at = now_utc()
        await db.commit()


async def _finalize(
    session_factory: async_sessionmaker[AsyncSession], batch_id: str
) -> None:
    """整批处理结束后，汇总状态并清理暂存文件。

    批次状态规则：
        没有任何失败 → succeeded；
        全部失败     → failed；
        部分失败     → partial。
    只有“没有未完成任务”时才落最终状态，避免任务进程中途崩溃后
    批次被误标成完成。

    为什么成功后才清理暂存目录：
        失败项重试需要原始文件；整批没有失败时，原始内容已经保存在
        每篇文档自己的目录下，暂存副本就不再需要了。
    """
    async with session_factory() as db:
        batch = await db.get(ImportBatch, batch_id)
        if batch is None:
            return
        rows = (
            await db.execute(
                select(IngestionJob.status, func.count(IngestionJob.id))
                .where(IngestionJob.batch_id == batch_id)
                .group_by(IngestionJob.status)
            )
        ).all()
        counts = {status: int(count) for status, count in rows}
        total = sum(counts.values())
        failed = counts.get("failed", 0) + counts.get("dead", 0)
        unfinished = counts.get("pending", 0) + counts.get("running", 0)

        previous = batch.stats or {}
        batch.stats = {
            "total": total,
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0),
            "succeeded": counts.get("succeeded", 0),
            "failed": failed,
            "skipped": counts.get("skipped", 0),
            "images": previous.get("images", 0),
            "ignored": previous.get("ignored", 0),
            "unusedImages": previous.get("unusedImages", 0),
            # 明细只在创建批次时计算一次，汇总阶段必须原样带过去，
            # 否则批次一结束清单就变成空数组，前端就看不到是哪几张了。
            "unusedImagePaths": previous.get("unusedImagePaths", []),
        }
        if unfinished == 0:
            if failed == 0:
                batch.status = "succeeded"
            elif failed == total:
                batch.status = "failed"
            else:
                batch.status = "partial"
            batch.finished_at = now_utc()
        await db.commit()

    if unfinished == 0 and failed == 0:
        get_storage().delete_prefix(f"kb/imports/{batch_id}")


async def _mark_batch_failed(
    session_factory: async_sessionmaker[AsyncSession],
    batch_id: str,
    exc: Exception,
) -> None:
    """后台任务整体异常时的兜底：把批次标成失败并保留原因。

    单个文件的异常已经在 _process_job 内处理；这里只兜底数据库连接、
    存储不可用这类整批级故障，避免前端永远停在“处理中”。
    """
    try:
        async with session_factory() as db:
            batch = await db.get(ImportBatch, batch_id)
            if batch is None:
                return
            batch.status = "failed"
            batch.error_message = kb_service.error_text(exc)[:500]
            batch.finished_at = now_utc()
            await db.commit()
    except Exception:  # noqa: BLE001 - 兜底失败时不能再抛出，否则会盖住原始异常
        return


async def run_batch(
    session_factory: async_sessionmaker[AsyncSession], batch_id: str
) -> None:
    """后台任务入口：依次处理批次里所有待执行文件。

    为什么先取一遍任务编号，再逐个处理：
        列表用的是一次短查询，处理阶段每个文件独立提交。
        这样前端轮询进度时能看到“已成功几篇、还剩几篇”，
        而不是等整批结束才一次性变化。
    """
    try:
        async with session_factory() as db:
            batch = await db.get(ImportBatch, batch_id)
            if batch is None:
                return
            batch.status = "running"
            batch.error_message = None
            batch.finished_at = None
            await db.commit()
            job_ids = (
                await db.scalars(
                    select(IngestionJob.id)
                    .where(
                        IngestionJob.batch_id == batch_id,
                        IngestionJob.status == "pending",
                    )
                    .order_by(IngestionJob.created_at, IngestionJob.id)
                )
            ).all()

        for job_id in job_ids:
            await _process_job(session_factory, job_id)
        await _finalize(session_factory, batch_id)
    except Exception as exc:  # noqa: BLE001 - 后台任务不能把异常抛给已返回的请求
        await _mark_batch_failed(session_factory, batch_id, exc)


def _job_payload(job: IngestionJob) -> dict[str, Any]:
    """把任务表的一行转换成前端展示结构。"""
    payload = job.payload or {}
    result = job.result or {}
    return {
        "id": job.id,
        "relativePath": payload.get("relativePath", ""),
        "filename": payload.get("filename", ""),
        "title": payload.get("title", ""),
        "status": job.status,
        "errorMessage": job.error_message,
        "attempts": job.attempts,
        "documentId": result.get("documentId"),
        "chunkCount": result.get("chunkCount", 0),
        "imageCount": result.get("imageCount", 0),
        "unmatchedImageCount": result.get("unmatchedImageCount", 0),
        "updatedAt": iso(job.updated_at),
    }


def _batch_payload(batch: ImportBatch, jobs: list[IngestionJob]) -> dict[str, Any]:
    """批次详情：整体状态、统计，以及每个文件的处理结果。"""
    return {
        "id": batch.id,
        "label": batch.source_uri,
        "status": batch.status,
        "stats": batch.stats or {},
        "errorMessage": batch.error_message,
        "createdAt": iso(batch.created_at),
        "finishedAt": iso(batch.finished_at),
        "items": [_job_payload(job) for job in jobs],
    }


async def get_batch(db: AsyncSession, batch_id: str) -> dict[str, Any]:
    """查询批次详情，供前端轮询进度与查看失败清单。"""
    batch = await db.get(ImportBatch, batch_id)
    if batch is None:
        raise AppError("KB_IMPORT_NOT_FOUND", "导入批次不存在", status_code=404)
    jobs = (
        await db.scalars(
            select(IngestionJob)
            .where(IngestionJob.batch_id == batch_id)
            .order_by(IngestionJob.created_at, IngestionJob.id)
        )
    ).all()
    return _batch_payload(batch, list(jobs))


async def retry_failed(
    db: AsyncSession,
    admin: AdminUser,
    batch_id: str,
) -> tuple[dict[str, Any], int]:
    """把批次里失败的文件重新放回待执行状态。

    为什么只重试失败项：
        成功的文档已经写入知识库，再跑一次只会被内容去重跳过，
        白白消耗时间；失败的才需要重新解析。
    为什么重试前要检查批次不在处理中：
        处理中重置任务状态，可能让同一个文件被两个后台任务同时处理。
        乐观锁能兜住大部分情况，但直接拒绝更清晰。
    """
    batch = await db.get(ImportBatch, batch_id)
    if batch is None:
        raise AppError("KB_IMPORT_NOT_FOUND", "导入批次不存在", status_code=404)
    if batch.status == "running":
        raise AppError(
            "KB_IMPORT_RUNNING", "批次正在处理中，请稍后再试", status_code=409
        )

    jobs = (
        await db.scalars(
            select(IngestionJob).where(
                IngestionJob.batch_id == batch_id,
                IngestionJob.status.in_(("failed", "dead")),
            )
        )
    ).all()
    if not jobs:
        return await get_batch(db, batch_id), 0

    now = now_utc()
    for job in jobs:
        job.status = "pending"
        job.error_message = None
        job.locked_at = None
        job.locked_by = None
        job.run_after = now
        job.updated_at = now
    batch.status = "pending"
    batch.finished_at = None
    batch.error_message = None
    write_audit(
        db,
        actor=admin,
        action="kb.import.retry",
        target_type="import_batch",
        target_id=batch_id,
        after={"jobIds": [job.id for job in jobs]},
    )
    await db.commit()
    return await get_batch(db, batch_id), len(jobs)
