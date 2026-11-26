"""知识库后台接口。

接口分为四组：
1. 文档：上传（只切片）、列表（含待索引切片信息）、详情、重新切片、
   建立索引、删除、查看切片；
2. 批量导入：创建批次、查询进度、重试失败项；
3. 索引版本：列表、新建、启用；
4. 检索测试：用真实问题验证召回效果。

为什么不再单独提供“切片列表”接口：
    “待建立索引”本来就是文档列表的一个子集，单独开接口会让前端维护两个列表，
    同一篇文档在两处出现。现在文档列表直接返回待索引切片数量与参数，
    页面只展示一个列表，运营不需要来回对照。

为什么上传和建立索引要分成两个接口：
切片只做文本处理，嵌入要调用外部模型、按量计费。拆开后运营可以先检查
切片质量，再决定是否花钱生成向量；嵌入失败也只重试建立索引，不用重新上传。

为什么批量导入还要单独一组接口：
一次导入包含多个文件，请求不可能等所有文件处理完再返回。
创建批次后立刻返回，前端轮询批次进度，失败的文件可以单独重试。

权限拆成两个：
- kb.document.manage：能改数据（上传、批量导入、删除、重建）；
- kb.search.test：只做检索测试，不改数据。
这样可以让只负责调参的同事测试效果，但不能删除文档。
"""

import json

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    Request,
    UploadFile,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import AdminPrincipal, client_ip, require_permission
from app.core.errors import AppError
from app.core.responses import ok
from app.db.session import get_db, get_session_factory
from app.schemas import (
    KbBatchDeleteRequest,
    KbBatchOperationRequest,
    KbIndexVersionCreateRequest,
    KbSearchTestRequest,
)
from app.services import kb_import_service, kb_recipe_service, kb_service

router = APIRouter(prefix="/admin/kb", tags=["admin-kb"])


@router.get("/documents")
async def list_documents(
    status: str | None = Query(default=None, max_length=20),
    keyword: str | None = Query(default=None, max_length=60),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """文档列表：按页码分页，返回总数、当前页码与每页条数。"""
    return ok(
        await kb_service.list_documents(
            db,
            status=status,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    )


@router.post("/documents")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(default=None, max_length=120),
    images: list[UploadFile] = File(default=[]),
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """上传 Markdown 或纯文本文档，只做解析与切片，不调用嵌入模型。

    图片是可选字段，可以一次选择多张：后台按文件名匹配 Markdown 里的
    `![说明](./图片.webp)` 引用，保存后把地址改写成本服务的可访问地址。
    这样预览切片时图片能直接显示，而不是留下一行图片语法。

    切片失败仍返回 200，但在 message 与文档状态中说明原因：
    文件已经保存，运营可以重新切片或删除，不需要重新上传。
    """
    data = await file.read()
    image_payloads = [
        (image.filename or "image.png", await image.read()) for image in images
    ]
    payload, error = await kb_service.upload_document(
        db,
        principal.admin,
        title=title,
        filename=file.filename or "document.md",
        mime=file.content_type,
        data=data,
        ip=client_ip(request),
        images=image_payloads,
    )
    if error:
        return ok(payload, f"文档已保存，但切片失败：{error}")
    message = "文档已上传并完成切片，请到切片列表建立索引"
    if payload.get("imageCount"):
        message += f"；已关联 {payload['imageCount']} 张图片"
    if payload.get("unmatchedImageCount"):
        message += f"，另有 {payload['unmatchedImageCount']} 处图片引用未匹配到上传文件"
    return ok(payload, message)


def _parse_paths(raw: str | None) -> list[str] | None:
    """解析文件夹上传时前端提交的相对路径列表。

    浏览器选择文件夹后，文件对象里带有 `webkitRelativePath`，
    但 multipart 表单不会自动携带这个值，因此前端把它序列化成 JSON
    （与 files 顺序一一对应）一起提交。这里只做格式校验，
    真正的路径安全校验在导入服务里完成。

    为什么格式不对时选择报错而不是忽略：
        路径对不上会导致图片目录匹配失效，静默忽略会让运营以为
        “文件夹上传成功”，但配图全丢了，问题更难发现。
    """
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AppError(
            "KB_IMPORT_PATHS_INVALID",
            "文件路径列表不是合法的 JSON",
            status_code=400,
        ) from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AppError(
            "KB_IMPORT_PATHS_INVALID",
            "文件路径列表必须是字符串数组",
            status_code=400,
        )
    return value


@router.post("/import-batches")
async def create_import_batch(
    request: Request,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(default=[]),
    archive: UploadFile | None = File(default=None),
    paths: str | None = Form(default=None),
    label: str | None = Form(default=None, max_length=255),
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
    session_factory=Depends(get_session_factory),
):
    """创建批量导入批次：支持多文件、文件夹和 ZIP 压缩包。

    这个接口只做三件事：接收、校验、生成任务，然后立刻返回批次编号。
    真正的解析与切片交给后台任务，避免上百个文件把请求拖到超时。

    为什么把后台任务函数和会话工厂都传进去：
        后台任务执行时，当前请求的数据库会话已经关闭，必须自己创建会话。
        会话工厂通过依赖注入传入，测试环境就能替换成临时数据库，
        不会把测试数据写进开发库。
    """
    file_payloads = [
        (item.filename or "document.md", await item.read()) for item in files
    ]
    archive_payload = None
    if archive is not None and archive.filename:
        # 先看声明大小再读：避免把一个超大压缩包整个读进内存才拒绝。
        kb_import_service.validate_archive_size(archive.size)
        archive_payload = (archive.filename, await archive.read())

    payload = await kb_import_service.create_batch(
        db,
        principal.admin,
        label=label,
        files=file_payloads,
        paths=_parse_paths(paths),
        archive=archive_payload,
        ip=client_ip(request),
    )
    background_tasks.add_task(
        kb_import_service.run_batch, session_factory, payload["id"]
    )
    return ok(payload, "批次已创建，正在后台解析")


@router.get("/import-batches/{batch_id}")
async def get_import_batch(
    batch_id: str,
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """查询批次进度与每个文件的处理结果，前端按固定间隔轮询。"""
    return ok(await kb_import_service.get_batch(db, batch_id))


@router.post("/import-batches/{batch_id}/retry")
async def retry_import_batch(
    batch_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
    session_factory=Depends(get_session_factory),
):
    """只重试批次里失败的文件，已经成功的文件不会再次解析。"""
    payload, retried = await kb_import_service.retry_failed(
        db, principal.admin, batch_id
    )
    if retried == 0:
        return ok(payload, "没有失败项需要重试")
    background_tasks.add_task(kb_import_service.run_batch, session_factory, batch_id)
    return ok(payload, f"已重新提交 {retried} 个文件")


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await kb_service.get_document(db, document_id))


@router.post("/documents/{document_id}/rechunk")
async def rechunk_document(
    document_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """按当前启用索引版本的参数重新切片，结果放回切片列表。

    只切片、不嵌入：旧索引在新索引建立前保持可用。
    """
    payload, error = await kb_service.rechunk_document(
        db, principal.admin, document_id, client_ip(request)
    )
    if error:
        return ok(payload, f"重新切片失败：{error}")
    return ok(payload, "已重新切片，请到切片列表建立索引")


@router.post("/documents/{document_id}/index")
async def build_document_index(
    document_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """把切片列表里的切片建立成可检索的索引（调用嵌入模型生成向量）。"""
    payload, error = await kb_service.build_index(
        db, principal.admin, document_id, client_ip(request)
    )
    if error:
        return ok(payload, f"建立索引失败：{error}")
    return ok(payload, "索引已建立，文档可用于检索")


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """删除文档、切片与原始文件，操作写入审计日志。"""
    return ok(
        await kb_service.delete_document(
            db, principal.admin, document_id, client_ip(request)
        ),
        "文档已删除",
    )


@router.post("/documents/{document_id}/recipe-draft")
async def generate_recipe_draft(
    document_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """把文档按固定模板解析成菜谱草稿，供运营在菜谱管理里核对后发布。

    上传成功时后端已经自动尝试生成一次；这个接口用于两类场景：
    1. 旧文档补生成；
    2. 运营改过文档内容后重新生成（已发布的菜谱不会被覆盖）。
    """
    result = await kb_recipe_service.generate_draft(
        db, principal.admin, document_id, client_ip(request)
    )
    return ok(result, result["message"])


@router.post("/documents/batch-delete")
async def batch_delete_documents(
    body: KbBatchDeleteRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """批量删除文档，逐条返回结果。

    为什么用 POST 而不是 DELETE：
    DELETE 请求不应该携带请求体（部分代理和客户端会直接丢掉），
    而批量删除需要一次传多个编号，POST + 请求体是最稳妥的写法。
    """
    data = await kb_service.batch_delete_documents(
        db, principal.admin, body.document_ids, client_ip(request)
    )
    return ok(data, f"已删除 {data['succeeded']} 篇，失败 {data['failed']} 篇")


@router.post("/documents/batch-rechunk")
async def batch_rechunk_documents(
    body: KbBatchOperationRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """批量重新切片：逐篇执行，某篇失败不影响其他篇。"""
    data = await kb_service.batch_rechunk_documents(
        db, principal.admin, body.document_ids, client_ip(request)
    )
    return ok(
        data,
        f"重新切片完成：成功 {data['succeeded']} 篇，失败 {data['failed']} 篇",
    )


@router.post("/documents/batch-recipe-draft")
async def batch_generate_recipe_drafts(
    body: KbBatchOperationRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """批量生成菜谱草稿：已发布的菜谱会被跳过，不会覆盖人工修改。"""
    data = await kb_service.batch_generate_recipe_drafts(
        db, principal.admin, body.document_ids, client_ip(request)
    )
    return ok(
        data,
        f"生成菜谱草稿完成：成功 {data['succeeded']} 篇，"
        f"跳过 {data['skipped']} 篇，失败 {data['failed']} 篇",
    )


@router.post("/documents/batch-index")
async def batch_build_index(
    body: KbBatchOperationRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """批量建立索引：逐篇调用嵌入模型，没有待索引切片的文档自动跳过。"""
    data = await kb_service.batch_build_index(
        db, principal.admin, body.document_ids, client_ip(request)
    )
    return ok(
        data,
        f"建立索引完成：成功 {data['succeeded']} 篇，"
        f"跳过 {data['skipped']} 篇，失败 {data['failed']} 篇",
    )


@router.get("/documents/{document_id}/chunks")
async def list_chunks(
    document_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """分页查看切片，用于人工检查切片长度与内容是否合理。"""
    return ok(
        await kb_service.list_chunks(db, document_id, offset=offset, limit=limit)
    )


@router.get("/index-versions")
async def list_index_versions(
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await kb_service.list_index_versions(db))


@router.post("/index-versions")
async def create_index_version(
    body: KbIndexVersionCreateRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """新建索引版本。新版本不会自动切换，需要显式启用。"""
    return ok(
        await kb_service.create_index_version(
            db, principal.admin, body, client_ip(request)
        ),
        "索引版本已创建",
    )


@router.post("/index-versions/{version_id}/activate")
async def activate_index_version(
    version_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """启用指定版本，旧的启用版本自动归档。"""
    return ok(
        await kb_service.activate_index_version(
            db, principal.admin, version_id, client_ip(request)
        ),
        "索引版本已启用",
    )


@router.post("/search-test")
async def search_test(
    body: KbSearchTestRequest,
    principal: AdminPrincipal = Depends(require_permission("kb.search.test")),
    db: AsyncSession = Depends(get_db),
):
    """检索测试：把问题转成向量，返回最相似的片段与相似度。"""
    return ok(await kb_service.search_test(db, principal.admin, body))
