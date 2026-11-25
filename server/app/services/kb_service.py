"""知识库业务服务：文档上传、切片、建立索引、检索测试。

整体流程（2026-11-24 起把“切片”和“建立向量”拆成两步）：
1. 运营上传 Markdown 或纯文本，服务端计算 SHA-256 去重并保存原文件；
2. 按当前启用索引版本的参数切片（标题分节 + 段落累积 + 相邻重叠），
   切片写入 kb_draft_chunks，文档状态变为 chunked（待建立索引）；
3. 运营在后台“切片列表”里检查切片，点“去新建索引”，确认后建立索引；
4. 建立索引时调用嵌入模型，把每个切片转成 1024 维向量，
   切片连同向量写入 kb_chunks，文档状态变为 ready；
5. 检索测试把问题转成向量，按余弦相似度返回最接近的片段。

为什么要把两步拆开：
切片是纯文本处理，快且不花钱；嵌入要调用外部模型，慢、按量计费，
而且如果切得不好，嵌入的额度就白花了。拆开之后运营可以先用低成本的方式
检查切片质量，确认没问题再花钱生成向量；失败时也只重试嵌入，不需要重新上传。

为什么把处理过程设计成同步状态机（parsing → chunking → chunked →
indexing → ready）：
当前文档量小，同步处理能让运营操作后立刻看到结果，也少一套消息队列和
后台进程。状态机让每一步都落库，以后改成异步任务时，
消费者只需要读取“非 ready”的文档继续处理，业务代码不用重写。

为什么检索统一用原生 SQL：
pgvector 的 `<=>`（余弦距离运算符）和 `CAST(... AS vector)` 属于
PostgreSQL 扩展语法，SQLAlchemy 的 ORM 查询表达式无法完整表达；
同时 asyncpg 默认不认识 vector 类型，原生 SQL 传字符串再 CAST
可以完全绕开驱动的类型编解码，写入和检索行为最可控。
"""

import hashlib
import json
import math
import re
import time
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import iso
from app.core.errors import AppError
from app.core.security import new_id
from app.db.models import AdminUser
from app.db.rag_models import (
    KB_EMBEDDING_DIMENSIONS,
    KbChunk,
    KbDocument,
    KbDraftChunk,
    KbIndexVersion,
)
from app.schemas import KbIndexVersionCreateRequest, KbSearchTestRequest
from app.services import embedding_service
from app.services.audit_service import write_audit
from app.services.storage import get_storage
from app.services.text_chunker import split_document
from app.utils.time import now_utc

# 单个文档最大 5 MB。知识文档是文字内容，5 MB 已经足够容纳很长的手册；
# 限制大小可以避免一次上传长时间占用服务进程和嵌入接口额度。
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
ALLOWED_SUFFIXES = {".md", ".txt"}
MAX_DOCUMENT_LIMIT = 200
MAX_CHUNK_PAGE = 100


def _safe_filename(raw: str) -> str:
    """清洗上传文件名，只保留字母、数字、汉字和少量安全符号。

    文件名会被拼进存储路径，必须防止 `../` 这类目录穿越字符。
    """
    name = Path(raw or "document.md").name
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", name).strip("._")
    return cleaned[:120] or "document.md"


def _decode_text(data: bytes) -> str:
    """按 UTF-8 解码，兼容带字节顺序标记（BOM）的文件。

    不做编码猜测：编码猜错会得到一堆乱码，而且很难被发现；
    直接提示运营另存为 UTF-8 更可靠。
    """
    try:
        text_content = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError(
            "KB_FILE_ENCODING",
            "文件不是 UTF-8 编码，请另存为 UTF-8 后重新上传",
            status_code=400,
        ) from exc
    if not text_content.strip():
        raise AppError("KB_FILE_EMPTY", "文件内容为空", status_code=400)
    return text_content


def _vector_literal(vector: list[float]) -> str:
    """把向量转成 pgvector 能识别的字符串格式：[0.1,0.2,...]。

    为什么不直接把 Python 列表交给数据库驱动：
    asyncpg 没有内置 vector 类型编解码，传字符串再用 CAST 转成 vector
    是最稳定、最少依赖的做法。
    """
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    """计算两个向量的余弦相似度，取值范围 -1 到 1。

    余弦相似度只看方向不看长度，适合文本向量：
    “番茄炒蛋”和“西红柿炒鸡蛋”语义接近，向量方向也接近。
    长度为 0 的向量没有方向，直接返回 0，避免除零。
    """
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _error_text(exc: Exception) -> str:
    """把异常转换成可展示的错误说明。

    业务异常本身就有中文说明；未知异常带上类型名，
    方便排查时不至于只剩一句“失败”。
    """
    if isinstance(exc, (AppError, embedding_service.EmbeddingError)):
        return exc.message
    return f"{type(exc).__name__}: {exc}"


def _version_payload(version: KbIndexVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "name": version.name,
        "embedProvider": version.embed_provider,
        "embedModel": version.embed_model,
        "dimensions": version.dimensions,
        "chunkSize": version.chunk_size,
        "chunkOverlap": version.chunk_overlap,
        "status": version.status,
        "createdAt": iso(version.created_at),
        "activatedAt": iso(version.activated_at),
    }


def _document_payload(doc: KbDocument, chunk_count: int = 0) -> dict[str, Any]:
    return {
        "id": doc.id,
        "title": doc.title,
        "sourceType": doc.source_type,
        "mime": doc.mime,
        "bytes": doc.bytes,
        "checksum": doc.checksum,
        "status": doc.status,
        "errorMessage": doc.error_message,
        "indexVersionId": doc.index_version_id,
        "uploadedBy": doc.uploaded_by,
        "chunkCount": chunk_count,
        "createdAt": iso(doc.created_at),
        "updatedAt": iso(doc.updated_at),
    }


async def _chunk_count(db: AsyncSession, document_id: str) -> int:
    """已建立索引的切片数量（kb_chunks）。"""
    total = await db.scalar(
        select(func.count()).select_from(KbChunk).where(KbChunk.document_id == document_id)
    )
    return int(total or 0)


async def _draft_count(db: AsyncSession, document_id: str) -> int:
    """待建立索引的切片数量（kb_draft_chunks）。"""
    total = await db.scalar(
        select(func.count())
        .select_from(KbDraftChunk)
        .where(KbDraftChunk.document_id == document_id)
    )
    return int(total or 0)


async def _effective_chunk_count(db: AsyncSession, document_id: str) -> int:
    """展示用的切片数：有半成品时优先显示半成品数量。

    重新切片后旧索引还在、能继续被检索，但运营最关心的是“这次切出来多少”；
    因此只要存在待索引切片，就展示它，建立索引后再回到已索引数量。
    """
    drafts = await _draft_count(db, document_id)
    if drafts:
        return drafts
    return await _chunk_count(db, document_id)


async def _active_version(db: AsyncSession) -> KbIndexVersion | None:
    """取当前启用的索引版本。

    正常情况下同时只有一个 active；如果历史数据里出现多个，
    按创建时间取最新的一个，保证检索行为可预期。
    """
    return await db.scalar(
        select(KbIndexVersion)
        .where(KbIndexVersion.status == "active")
        .order_by(KbIndexVersion.created_at.desc(), KbIndexVersion.id.desc())
    )


async def ensure_active_version(db: AsyncSession) -> KbIndexVersion:
    """确保至少存在一个启用的索引版本。

    首次部署还没有任何版本时自动创建一个默认版本，
    这样运营上传第一份文档就能直接成功，不需要先手工建版本。
    """
    version = await _active_version(db)
    if version is not None:
        return version
    version = KbIndexVersion(
        id=new_id("kbv"),
        name="默认索引",
        embed_provider="",
        embed_model="",
        dimensions=KB_EMBEDDING_DIMENSIONS,
        chunk_size=400,
        chunk_overlap=80,
        status="active",
        created_at=now_utc(),
        activated_at=now_utc(),
    )
    db.add(version)
    await db.flush()
    return version


async def list_index_versions(db: AsyncSession) -> dict[str, Any]:
    versions = (
        await db.scalars(
            select(KbIndexVersion).order_by(
                KbIndexVersion.created_at.desc(), KbIndexVersion.id.desc()
            )
        )
    ).all()
    return {"items": [_version_payload(version) for version in versions]}


async def create_index_version(
    db: AsyncSession,
    admin: AdminUser,
    body: KbIndexVersionCreateRequest,
    ip: str | None,
) -> dict[str, Any]:
    """新建一个索引版本。

    新版本默认是 building，不会自动切换：
    如果自动切换，旧版本的文档会立刻从检索结果里消失，
    运营还没验证新参数就已经影响线上问答。
    """
    version = KbIndexVersion(
        id=new_id("kbv"),
        name=body.name.strip(),
        embed_provider="",
        embed_model="",
        dimensions=KB_EMBEDDING_DIMENSIONS,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
        status="building",
        created_at=now_utc(),
    )
    db.add(version)
    write_audit(
        db,
        actor=admin,
        action="kb.index_version.create",
        target_type="kb_index_version",
        target_id=version.id,
        after={
            "name": version.name,
            "chunkSize": version.chunk_size,
            "chunkOverlap": version.chunk_overlap,
        },
        ip=ip,
    )
    await db.commit()
    return _version_payload(version)


async def activate_index_version(
    db: AsyncSession,
    admin: AdminUser,
    version_id: str,
    ip: str | None,
) -> dict[str, Any]:
    """启用指定版本：旧 active 归档，新版本生效。

    切换只影响检索读取哪个版本，不会删除旧版本的数据，
    发现问题时可以立刻切回旧版本。
    """
    version = await db.get(KbIndexVersion, version_id)
    if version is None:
        raise AppError("KB_INDEX_VERSION_NOT_FOUND", "索引版本不存在", status_code=404)

    previous = (
        await db.scalars(
            select(KbIndexVersion).where(
                KbIndexVersion.status == "active", KbIndexVersion.id != version.id
            )
        )
    ).all()
    for item in previous:
        item.status = "archived"
    version.status = "active"
    version.activated_at = now_utc()
    write_audit(
        db,
        actor=admin,
        action="kb.index_version.activate",
        target_type="kb_index_version",
        target_id=version.id,
        after={"name": version.name, "archived": [item.id for item in previous]},
        ip=ip,
    )
    await db.commit()
    return _version_payload(version)


async def list_documents(
    db: AsyncSession,
    *,
    status: str | None = None,
    keyword: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """文档列表，附带每个文档的切片数量。

    切片数量用一次分组查询批量取，避免每个文档都查一次数据库
    （也就是常见的“N + 1 查询”问题）。
    """
    limit = min(max(limit, 1), MAX_DOCUMENT_LIMIT)
    conditions = []
    if status:
        conditions.append(KbDocument.status == status.strip())
    if keyword:
        conditions.append(KbDocument.title.contains(keyword.strip()))

    rows = (
        await db.scalars(
            select(KbDocument)
            .where(*conditions)
            .order_by(KbDocument.created_at.desc(), KbDocument.id.desc())
            .limit(limit)
        )
    ).all()
    counts: dict[str, int] = {}
    draft_counts: dict[str, int] = {}
    if rows:
        document_ids = [doc.id for doc in rows]
        indexed_rows = (
            await db.execute(
                select(KbChunk.document_id, func.count(KbChunk.id))
                .where(KbChunk.document_id.in_(document_ids))
                .group_by(KbChunk.document_id)
            )
        ).all()
        counts = {document_id: int(count) for document_id, count in indexed_rows}
        draft_rows = (
            await db.execute(
                select(KbDraftChunk.document_id, func.count(KbDraftChunk.id))
                .where(KbDraftChunk.document_id.in_(document_ids))
                .group_by(KbDraftChunk.document_id)
            )
        ).all()
        draft_counts = {document_id: int(count) for document_id, count in draft_rows}
    return {
        "items": [
            _document_payload(
                doc, draft_counts.get(doc.id) or counts.get(doc.id, 0)
            )
            for doc in rows
        ]
    }


def _split_text(
    text_content: str,
    title: str,
    version: KbIndexVersion,
) -> list[Any]:
    """按索引版本的参数把正文切成切片。

    抽成独立函数的原因：上传和“重新切片”必须使用完全相同的切片规则，
    否则同一个文件在不同入口会切出不同结果，排查问题时无法复现。
    """
    chunks = split_document(
        text_content,
        title=title,
        target_chars=version.chunk_size,
        max_chars=version.chunk_size * 2,
        overlap_chars=version.chunk_overlap,
    )
    if not chunks:
        raise AppError("KB_DOCUMENT_EMPTY", "文档没有可用正文，无法生成切片")
    return chunks


async def _save_drafts(
    db: AsyncSession,
    *,
    document_id: str,
    version: KbIndexVersion,
    chunks: list[Any],
) -> None:
    """把一个文档切好的切片写入 kb_draft_chunks（切片列表）。

    这里不生成向量，也不删除旧索引：新切片只是“候选”，
    运营点“建立索引”之后才会替换线上正在使用的那一套切片。
    """
    created_at = now_utc()
    for ordinal, chunk in enumerate(chunks):
        db.add(
            KbDraftChunk(
                id=new_id("kbdft"),
                document_id=document_id,
                ordinal=ordinal,
                content=chunk.content,
                token_count=chunk.token_count,
                chunk_size=version.chunk_size,
                chunk_overlap=version.chunk_overlap,
                chunk_metadata=chunk.metadata,
                created_at=created_at,
            )
        )


async def _insert_chunks(
    db: AsyncSession,
    *,
    document_id: str,
    version_id: str,
    chunks: list[Any],
    vectors: list[list[float]],
) -> None:
    """把待索引切片和向量写入 kb_chunks。

    PostgreSQL 走原生 SQL + CAST，SQLite（单元测试）把向量存成 JSON 文本。
    两种实现的差异只在这一个函数里，上层完全不感知数据库类型。
    """
    dialect = db.get_bind().dialect.name
    created_at = now_utc()
    if dialect == "postgresql":
        statement = text(
            """
            INSERT INTO kb_chunks
                (id, document_id, index_version_id, ordinal, content,
                 token_count, embedding, "metadata", created_at)
            VALUES
                (:id, :document_id, :index_version_id, :ordinal, :content,
                 :token_count, CAST(:embedding AS vector), :metadata, :created_at)
            """
        )
        for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors, strict=False)):
            await db.execute(
                statement,
                {
                    "id": new_id("kbc"),
                    "document_id": document_id,
                    "index_version_id": version_id,
                    "ordinal": ordinal,
                    "content": chunk.content,
                    "token_count": chunk.token_count,
                    "embedding": _vector_literal(vector),
                    "metadata": json.dumps(chunk.chunk_metadata, ensure_ascii=False),
                    "created_at": created_at,
                },
            )
        return

    for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors, strict=False)):
        db.add(
            KbChunk(
                id=new_id("kbc"),
                document_id=document_id,
                index_version_id=version_id,
                ordinal=ordinal,
                content=chunk.content,
                token_count=chunk.token_count,
                embedding=json.dumps(vector),
                chunk_metadata=chunk.chunk_metadata,
                created_at=created_at,
            )
        )


async def _chunk_document(
    db: AsyncSession,
    doc: KbDocument,
    text_content: str,
    version: KbIndexVersion,
    admin: AdminUser,
    ip: str | None,
    *,
    action: str,
) -> None:
    """执行“切片 → 写入切片列表”，不调用嵌入模型。

    步骤：
    1. 状态改成 chunking，让后台能看到正在切片；
    2. 按参数切片；
    3. 清掉这个文档上一次留下的待索引切片（重复切片不能叠加）；
    4. 写入新的待索引切片，状态改成 chunked。
    """
    doc.status = "chunking"
    doc.error_message = None
    doc.updated_at = now_utc()
    await db.flush()

    chunks = _split_text(text_content, doc.title, version)

    await db.execute(delete(KbDraftChunk).where(KbDraftChunk.document_id == doc.id))
    await _save_drafts(
        db, document_id=doc.id, version=version, chunks=chunks
    )

    doc.status = "chunked"
    doc.error_message = None
    doc.updated_at = now_utc()
    write_audit(
        db,
        actor=admin,
        action=action,
        target_type="kb_document",
        target_id=doc.id,
        after={
            "title": doc.title,
            "chunkCount": len(chunks),
            "chunkSize": version.chunk_size,
            "chunkOverlap": version.chunk_overlap,
        },
        ip=ip,
    )
    await db.commit()


async def _run_chunk(
    db: AsyncSession,
    doc: KbDocument,
    text_content: str,
    version: KbIndexVersion,
    admin: AdminUser,
    ip: str | None,
    *,
    action: str,
) -> str | None:
    """执行切片并把失败原因记录到文档上。

    失败时先回滚（可能已有未提交的切片），再单独提交失败状态，
    这样运营在列表里能看到“失败 + 原因”，而不是永远停在“切片中”。
    """
    # 回滚会让 ORM 对象过期，之后再读 doc.id 可能触发同步 IO 并报错，
    # 因此先把编号取出来保存。
    document_id = doc.id
    try:
        await _chunk_document(db, doc, text_content, version, admin, ip, action=action)
        return None
    except Exception as exc:  # noqa: BLE001 - 需要把任何失败都记录到文档状态
        message = _error_text(exc)
        await db.rollback()
        failed = await db.get(KbDocument, document_id)
        if failed is not None:
            failed.status = "failed"
            failed.error_message = message[:500]
            failed.updated_at = now_utc()
            await db.commit()
        return message


async def _build_index(
    db: AsyncSession,
    doc: KbDocument,
    admin: AdminUser,
    ip: str | None,
) -> None:
    """把待索引切片转换成向量并写入 kb_chunks。

    流程：
    1. 取出切片列表中的切片（已按 ordinal 排序）；
    2. 状态改成 indexing，调用嵌入模型；
    3. 删除旧切片，写入新切片与向量（旧切片在新数据准备好后才替换）；
    4. 删除待索引切片，状态改成 ready。
    """
    version = await ensure_active_version(db)
    drafts = (
        await db.scalars(
            select(KbDraftChunk)
            .where(KbDraftChunk.document_id == doc.id)
            .order_by(KbDraftChunk.ordinal)
        )
    ).all()
    if not drafts:
        raise AppError(
            "KB_DRAFT_CHUNKS_MISSING",
            "没有待建立索引的切片，请先上传文档或重新切片",
            status_code=409,
        )

    doc.status = "indexing"
    doc.error_message = None
    doc.updated_at = now_utc()
    await db.flush()

    result = await embedding_service.embed_texts(
        db,
        [draft.content for draft in drafts],
        subject_ref=f"kb:{doc.id}",
    )

    # 同一文档只保留一套可用切片：旧版本切片整批替换，避免重复召回。
    await db.execute(delete(KbChunk).where(KbChunk.document_id == doc.id))
    await _insert_chunks(
        db,
        document_id=doc.id,
        version_id=version.id,
        chunks=list(drafts),
        vectors=result.vectors,
    )
    await db.execute(delete(KbDraftChunk).where(KbDraftChunk.document_id == doc.id))

    version.embed_provider = result.provider_name
    version.embed_model = result.model
    version.dimensions = result.dimensions
    doc.index_version_id = version.id
    doc.status = "ready"
    doc.error_message = None
    doc.updated_at = now_utc()
    write_audit(
        db,
        actor=admin,
        action="kb.document.index",
        target_type="kb_document",
        target_id=doc.id,
        after={
            "title": doc.title,
            "chunkCount": len(drafts),
            "indexVersionId": version.id,
            "embedModel": result.model,
        },
        ip=ip,
    )
    await db.commit()


async def _run_build(
    db: AsyncSession,
    doc: KbDocument,
    admin: AdminUser,
    ip: str | None,
) -> str | None:
    """执行建立索引，并把失败原因写回文档。

    失败时待索引切片会保留（事务回滚），运营修好嵌入模型配置后
    可以直接再次点“建立索引”，不用重新上传或重新切片。
    """
    document_id = doc.id
    try:
        await _build_index(db, doc, admin, ip)
        return None
    except Exception as exc:  # noqa: BLE001 - 需要把任何失败都记录到文档状态
        message = _error_text(exc)
        await db.rollback()
        failed = await db.get(KbDocument, document_id)
        if failed is not None:
            failed.status = "failed"
            failed.error_message = message[:500]
            failed.updated_at = now_utc()
            await db.commit()
        return message


async def upload_document(
    db: AsyncSession,
    admin: AdminUser,
    *,
    title: str | None,
    filename: str,
    mime: str | None,
    data: bytes,
    ip: str | None,
) -> tuple[dict[str, Any], str | None]:
    """上传文档：保存原文件并切片，不调用嵌入模型。

    返回：
        (文档展示数据, 失败原因)。失败原因为空表示切片成功；
        切片成功后文档状态是 chunked，需要再到切片列表建立索引。
    """
    safe_name = _safe_filename(filename)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise AppError(
            "KB_FILE_TYPE_UNSUPPORTED", "仅支持 .md 与 .txt 文件", status_code=400
        )
    if not data:
        raise AppError("KB_FILE_EMPTY", "文件内容为空", status_code=400)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise AppError(
            "KB_FILE_TOO_LARGE", "单个文件不能超过 5 MB", status_code=413
        )

    text_content = _decode_text(data)
    checksum = hashlib.sha256(data).hexdigest()
    existing = await db.scalar(
        select(KbDocument).where(KbDocument.checksum == checksum)
    )
    if existing is not None:
        raise AppError(
            "KB_DOCUMENT_DUPLICATE",
            f"相同内容的文档已存在：{existing.title}",
            status_code=409,
        )

    version = await ensure_active_version(db)
    document_id = new_id("kbd")
    storage_key = f"kb/{document_id}/{safe_name}"
    get_storage().put(storage_key, data)

    doc = KbDocument(
        id=document_id,
        title=(title or Path(safe_name).stem).strip()[:120],
        source_type="upload",
        storage_key=storage_key,
        mime=mime or ("text/markdown" if suffix == ".md" else "text/plain"),
        bytes=len(data),
        checksum=checksum,
        status="parsing",
        # 还没建立索引，因此先不指向任何版本；点“建立索引”成功后再写入。
        index_version_id=None,
        uploaded_by=admin.id,
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    db.add(doc)
    # 先提交文档记录：即使后面切片失败，文件与文档也不会凭空消失，
    # 运营可以看到失败原因并重新切片或删除。
    await db.commit()

    error = await _run_chunk(
        db, doc, text_content, version, admin, ip, action="kb.document.upload"
    )
    refreshed = await db.get(KbDocument, document_id)
    payload = _document_payload(refreshed, await _effective_chunk_count(db, document_id))
    return payload, error


async def get_document(db: AsyncSession, document_id: str) -> dict[str, Any]:
    doc = await db.get(KbDocument, document_id)
    if doc is None:
        raise AppError("KB_DOCUMENT_NOT_FOUND", "文档不存在", status_code=404)
    return _document_payload(doc, await _effective_chunk_count(db, document_id))


async def rechunk_document(
    db: AsyncSession,
    admin: AdminUser,
    document_id: str,
    ip: str | None,
) -> tuple[dict[str, Any], str | None]:
    """用当前启用索引版本的参数重新切片，结果放回切片列表。

    使用场景：调整了切片参数、换了索引版本，或者想重新检查切片质量。
    注意这里不再直接生成向量：旧索引在新索引建立前仍然可用，
    避免“点一下重建，线上检索立刻变空”。
    """
    doc = await db.get(KbDocument, document_id)
    if doc is None:
        raise AppError("KB_DOCUMENT_NOT_FOUND", "文档不存在", status_code=404)
    if doc.status in {"parsing", "chunking", "indexing"}:
        raise AppError("KB_DOCUMENT_BUSY", "文档正在处理中，请稍后再试", status_code=409)

    try:
        data = get_storage().read(doc.storage_key)
    except FileNotFoundError as exc:
        raise AppError(
            "KB_FILE_MISSING", "原始文件已丢失，请删除后重新上传", status_code=409
        ) from exc
    text_content = _decode_text(data)

    version = await ensure_active_version(db)
    doc.status = "parsing"
    doc.error_message = None
    doc.updated_at = now_utc()
    await db.commit()

    error = await _run_chunk(
        db, doc, text_content, version, admin, ip, action="kb.document.rechunk"
    )
    refreshed = await db.get(KbDocument, document_id)
    payload = _document_payload(refreshed, await _effective_chunk_count(db, document_id))
    return payload, error


async def build_index(
    db: AsyncSession,
    admin: AdminUser,
    document_id: str,
    ip: str | None,
) -> tuple[dict[str, Any], str | None]:
    """把切片列表里的切片建立成可检索的索引。

    返回：
        (文档展示数据, 失败原因)。失败原因为空表示建立成功。
    """
    doc = await db.get(KbDocument, document_id)
    if doc is None:
        raise AppError("KB_DOCUMENT_NOT_FOUND", "文档不存在", status_code=404)
    if doc.status in {"parsing", "chunking", "indexing"}:
        raise AppError("KB_DOCUMENT_BUSY", "文档正在处理中，请稍后再试", status_code=409)
    if await _draft_count(db, document_id) == 0:
        raise AppError(
            "KB_DRAFT_CHUNKS_MISSING",
            "没有待建立索引的切片，请先上传文档或重新切片",
            status_code=409,
        )

    error = await _run_build(db, doc, admin, ip)
    refreshed = await db.get(KbDocument, document_id)
    payload = _document_payload(refreshed, await _effective_chunk_count(db, document_id))
    return payload, error


async def list_chunk_sets(db: AsyncSession) -> dict[str, Any]:
    """切片列表：所有“切好但还没建立索引”的文档分组。

    用分组查询一次拿到每篇文档的切片数、切片参数和最早切片时间，
    避免先查文档再逐个查切片（N + 1 查询）。
    """
    rows = (
        await db.execute(
            select(
                KbDraftChunk.document_id,
                func.count(KbDraftChunk.id),
                func.max(KbDraftChunk.chunk_size),
                func.max(KbDraftChunk.chunk_overlap),
                func.min(KbDraftChunk.created_at),
            )
            .group_by(KbDraftChunk.document_id)
            .order_by(func.min(KbDraftChunk.created_at).desc())
        )
    ).all()
    if not rows:
        return {"items": []}

    document_ids = [row[0] for row in rows]
    documents = (
        await db.scalars(select(KbDocument).where(KbDocument.id.in_(document_ids)))
    ).all()
    document_map = {doc.id: doc for doc in documents}

    items: list[dict[str, Any]] = []
    for document_id, count, chunk_size, chunk_overlap, created_at in rows:
        doc = document_map.get(document_id)
        if doc is None:
            continue
        items.append(
            {
                "documentId": doc.id,
                "title": doc.title,
                "status": doc.status,
                "errorMessage": doc.error_message,
                "chunkCount": int(count),
                "chunkSize": int(chunk_size or 0),
                "chunkOverlap": int(chunk_overlap or 0),
                "createdAt": iso(created_at),
                "updatedAt": iso(doc.updated_at),
            }
        )
    return {"items": items}


async def delete_document(
    db: AsyncSession,
    admin: AdminUser,
    document_id: str,
    ip: str | None,
) -> dict[str, Any]:
    """删除文档、切片与原始文件。

    数据库记录直接物理删除：知识库文档不是用户内容，不需要保留软删除痕迹；
    删除动作本身会写入审计日志，可以追溯谁在什么时候删了什么。
    """
    doc = await db.get(KbDocument, document_id)
    if doc is None:
        raise AppError("KB_DOCUMENT_NOT_FOUND", "文档不存在", status_code=404)

    before = {"title": doc.title, "status": doc.status}
    await db.execute(delete(KbChunk).where(KbChunk.document_id == doc.id))
    await db.execute(delete(KbDraftChunk).where(KbDraftChunk.document_id == doc.id))
    get_storage().delete(doc.storage_key)
    write_audit(
        db,
        actor=admin,
        action="kb.document.delete",
        target_type="kb_document",
        target_id=doc.id,
        before=before,
        ip=ip,
    )
    await db.delete(doc)
    await db.commit()
    return {"id": document_id, "deleted": True}


async def list_chunks(
    db: AsyncSession,
    document_id: str,
    *,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """分页查看切片，用于人工检查切片质量。

    优先返回待索引切片：运营刚上传或重新切片后最想看的是这一批；
    没有待索引切片时再返回已经建立索引的切片。
    source 字段告诉前端当前看的是哪一批，避免运营误以为已生效。
    """
    doc = await db.get(KbDocument, document_id)
    if doc is None:
        raise AppError("KB_DOCUMENT_NOT_FOUND", "文档不存在", status_code=404)

    limit = min(max(limit, 1), MAX_CHUNK_PAGE)
    offset = max(offset, 0)
    total = await _draft_count(db, document_id)
    source = "draft"
    if total == 0:
        total = await _chunk_count(db, document_id)
        source = "indexed"

    if source == "draft":
        rows = (
            await db.scalars(
                select(KbDraftChunk)
                .where(KbDraftChunk.document_id == document_id)
                .order_by(KbDraftChunk.ordinal)
                .offset(offset)
                .limit(limit)
            )
        ).all()
    else:
        rows = (
            await db.scalars(
                select(KbChunk)
                .where(KbChunk.document_id == document_id)
                .order_by(KbChunk.ordinal)
                .offset(offset)
                .limit(limit)
            )
        ).all()

    items = [
        {
            "id": chunk.id,
            "ordinal": chunk.ordinal,
            "content": chunk.content,
            "tokenCount": chunk.token_count,
            "metadata": chunk.chunk_metadata,
        }
        for chunk in rows
    ]
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "hasMore": offset + len(items) < total,
        "source": source,
    }


async def _search_postgres(
    db: AsyncSession,
    *,
    version_id: str,
    vector: list[float],
    limit: int,
) -> list[dict[str, Any]]:
    """PostgreSQL + pgvector 的向量检索。

    `<=>` 是 pgvector 的余弦距离运算符，距离越小越相似；
    用 1 减去距离得到 0 到 1 的相似度，便于前端展示与设置阈值。
    """
    rows = (
        await db.execute(
            text(
                """
                SELECT c.id,
                       c.document_id,
                       c.ordinal,
                       c.content,
                       c."metadata" AS metadata,
                       1 - (c.embedding <=> CAST(:vector AS vector)) AS score,
                       d.title AS document_title
                FROM kb_chunks c
                JOIN kb_documents d ON d.id = c.document_id
                WHERE c.index_version_id = :version_id
                  AND c.embedding IS NOT NULL
                ORDER BY c.embedding <=> CAST(:vector AS vector)
                LIMIT :limit
                """
            ),
            {
                "vector": _vector_literal(vector),
                "version_id": version_id,
                "limit": limit,
            },
        )
    ).mappings().all()

    items: list[dict[str, Any]] = []
    for row in rows:
        metadata = row["metadata"]
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = None
        items.append(
            {
                "chunkId": row["id"],
                "documentId": row["document_id"],
                "documentTitle": row["document_title"],
                "ordinal": row["ordinal"],
                "content": row["content"],
                "score": round(float(row["score"]), 4),
                "metadata": metadata,
            }
        )
    return items


async def _search_sqlite(
    db: AsyncSession,
    *,
    version_id: str,
    vector: list[float],
) -> list[dict[str, Any]]:
    """SQLite 上的检索实现：读取向量文本，在 Python 里算余弦相似度。

    单元测试的文档量很小，逐条计算完全够用；
    生产环境不会走这条分支，所以不需要在 SQLite 上模拟 pgvector。
    """
    rows = (
        await db.execute(
            select(
                KbChunk.id,
                KbChunk.document_id,
                KbChunk.ordinal,
                KbChunk.content,
                KbChunk.chunk_metadata,
                KbChunk.embedding,
            ).where(KbChunk.index_version_id == version_id)
        )
    ).all()
    if not rows:
        return []

    document_ids = {row.document_id for row in rows}
    title_rows = (
        await db.execute(
            select(KbDocument.id, KbDocument.title).where(
                KbDocument.id.in_(document_ids)
            )
        )
    ).all()
    titles = {document_id: title for document_id, title in title_rows}

    items: list[dict[str, Any]] = []
    for row in rows:
        if not row.embedding:
            continue
        try:
            stored = json.loads(row.embedding)
        except (TypeError, json.JSONDecodeError):
            continue
        score = _cosine_similarity(vector, stored)
        items.append(
            {
                "chunkId": row.id,
                "documentId": row.document_id,
                "documentTitle": titles.get(row.document_id, ""),
                "ordinal": row.ordinal,
                "content": row.content,
                "score": round(score, 4),
                "metadata": row.chunk_metadata,
            }
        )
    return items


_KEYWORD_STOPWORDS = (
    "请问",
    "怎么",
    "如何",
    "什么",
    "哪些",
    "哪个",
    "哪里",
    "为什么",
    "能不能",
    "可不可以",
    "可以",
    "介绍",
    "一下",
    "告诉",
    "帮我",
)


def _keyword_terms(query: str) -> list[str]:
    """把自然语言问题拆成可用于 LIKE 的关键词。

    为什么需要拆：
        中文问题没有空格，直接拿整句“番茄怎么挑”去匹配，
        文档里通常不会出现一模一样的句子。这里去掉“怎么”“如何”等
        疑问词，再把连续中文切成二元组（番茄、茄挑），
        只要片段包含“番茄”就能被召回。
    返回：
        去重后的关键词，最多 8 个，避免 SQL 条件过长。
    """
    text = query.strip()
    if not text:
        return []

    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
    for word in _KEYWORD_STOPWORDS:
        cleaned = cleaned.replace(word, " ")
    compact = cleaned.replace(" ", "")

    terms: list[str] = [text]
    if compact and compact != text:
        terms.append(compact)
    for word in cleaned.split():
        if len(word) >= 2:
            terms.append(word)

    # 中文二元组：把“番茄挑”拆成“番茄”“茄挑”，提高字面召回率。
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", compact):
        if len(run) <= 4:
            terms.append(run)
        for index in range(len(run) - 1):
            terms.append(run[index : index + 2])

    deduped = list(dict.fromkeys(term for term in terms if len(term) >= 2))
    return deduped[:8]


def _keyword_pattern(term: str) -> str:
    """把关键词包成 LIKE 模式，并转义 % 和 _ 这两个通配符。"""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _keyword_score(content: str, terms: list[str]) -> float:
    """按“命中的最长关键词长度 / 最长关键词长度”给出 0 到 1 的分数。

    这个分数只用于关键词降级模式，表示字面匹配程度，
    不能和向量余弦相似度直接比较。
    """
    longest = max((len(term) for term in terms), default=0)
    if not longest:
        return 0.0
    lowered = content.lower()
    matched = max((len(term) for term in terms if term in lowered), default=0)
    return round(matched / longest, 4)


async def _search_keyword(
    db: AsyncSession,
    *,
    version_id: str,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    """嵌入模型不可用时的兜底检索：按关键词做字面匹配。

    和向量检索返回同样的片段结构，只把 score 换成关键词匹配度，
    上层接口通过 mode=keyword 告诉前端“这不是语义检索”。
    先限制最多取 200 个候选，再在 Python 里打分排序，
    避免一次把整库切片读进内存。
    """
    terms = _keyword_terms(query)
    if not terms:
        return []

    conditions = [
        KbChunk.content.ilike(_keyword_pattern(term), escape="\\") for term in terms
    ]
    rows = (
        await db.execute(
            select(
                KbChunk.id,
                KbChunk.document_id,
                KbChunk.ordinal,
                KbChunk.content,
                KbChunk.chunk_metadata,
                KbDocument.title,
            )
            .join(KbDocument, KbDocument.id == KbChunk.document_id)
            .where(
                KbChunk.index_version_id == version_id,
                or_(*conditions),
            )
            .limit(200)
        )
    ).all()

    items = [
        {
            "chunkId": row.id,
            "documentId": row.document_id,
            "documentTitle": row.title or "",
            "ordinal": row.ordinal,
            "content": row.content,
            "score": _keyword_score(row.content, terms),
            "metadata": row.chunk_metadata,
        }
        for row in rows
    ]
    items = [item for item in items if item["score"] > 0]
    items.sort(key=lambda item: (item["score"], -item["ordinal"]), reverse=True)
    return items[:limit]


async def search_test(
    db: AsyncSession,
    admin: AdminUser,
    body: KbSearchTestRequest,
) -> dict[str, Any]:
    """检索测试：把问题转成向量，返回最相似的片段。

    这是后台验证知识库是否好用的唯一手段：
    运营改完切片参数或换完模型后，应该先用真实问题试一次，
    确认排在前面的内容确实是想要的，再让问答功能使用。

    兜底策略：
        嵌入模型可能因为没配密钥、欠费、网络不通而不可用。
        这时如果直接抛错，整个检索功能就不可用了。为了让运营至少能
        确认“文档切片是否包含需要的内容”，这里自动降级为关键词检索：
        仍返回 200 和片段，用 mode=keyword 与 warning 说明当前不是语义检索。
        注意：降级只能检索已经写入数据库的切片；如果上传时就没有嵌入模型，
        文档仍会按原有逻辑进入 failed，不会产生切片。
    """
    started = time.perf_counter()
    version = await _active_version(db)
    if version is None:
        raise AppError(
            "KB_INDEX_NOT_READY", "尚未启用任何索引版本", status_code=409
        )

    limit = min(max(body.top_k, 1), 20)
    mode = "vector"
    warning: str | None = None

    try:
        result = await embedding_service.embed_texts(
            db, [body.query], subject_ref=f"admin:{admin.id}"
        )
    except embedding_service.EmbeddingError as exc:
        # 失败调用日志已经由 embed_texts 写入当前事务，稍后统一提交。
        mode = "keyword"
        warning = (
            f"嵌入模型暂不可用（{exc.message}），已自动降级为关键词检索；"
            "结果按字面匹配排序，不代表语义相似度"
        )
        items = await _search_keyword(
            db, version_id=version.id, query=body.query, limit=limit
        )
    else:
        vector = result.vectors[0]
        if db.get_bind().dialect.name == "postgresql":
            items = await _search_postgres(
                db, version_id=version.id, vector=vector, limit=limit
            )
        else:
            items = await _search_sqlite(db, version_id=version.id, vector=vector)

    filtered = [item for item in items if item["score"] >= body.threshold]
    filtered.sort(key=lambda item: item["score"], reverse=True)
    filtered = filtered[:limit]

    # 检索本身也会调用嵌入模型，需要提交调用日志。
    await db.commit()
    return {
        "query": body.query,
        "topK": limit,
        "threshold": body.threshold,
        "mode": mode,
        "warning": warning,
        "indexVersion": _version_payload(version),
        "tookMs": int((time.perf_counter() - started) * 1000),
        "items": filtered,
    }
