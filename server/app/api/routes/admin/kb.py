"""知识库后台接口。

接口分为四组：
1. 文档：上传（只切片）、列表、详情、重新切片、建立索引、删除、查看切片；
2. 切片列表：查看已切好但还没建立索引的文档；
3. 索引版本：列表、新建、启用；
4. 检索测试：用真实问题验证召回效果。

为什么上传和建立索引要分成两个接口：
切片只做文本处理，嵌入要调用外部模型、按量计费。拆开后运营可以先检查
切片质量，再决定是否花钱生成向量；嵌入失败也只重试建立索引，不用重新上传。

权限拆成两个：
- kb.document.manage：能改数据（上传、删除、重建）；
- kb.search.test：只做检索测试，不改数据。
这样可以让只负责调参的同事测试效果，但不能删除文档。
"""

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import AdminPrincipal, client_ip, require_permission
from app.core.responses import ok
from app.db.session import get_db
from app.schemas import KbIndexVersionCreateRequest, KbSearchTestRequest
from app.services import kb_service

router = APIRouter(prefix="/admin/kb", tags=["admin-kb"])


@router.get("/documents")
async def list_documents(
    status: str | None = Query(default=None, max_length=20),
    keyword: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=100, ge=1, le=200),
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """文档列表，包含处理状态与切片数量。"""
    return ok(await kb_service.list_documents(db, status=status, keyword=keyword, limit=limit))


@router.post("/documents")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(default=None, max_length=120),
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """上传 Markdown 或纯文本文档，只做解析与切片，不调用嵌入模型。

    切片失败仍返回 200，但在 message 与文档状态中说明原因：
    文件已经保存，运营可以重新切片或删除，不需要重新上传。
    """
    data = await file.read()
    payload, error = await kb_service.upload_document(
        db,
        principal.admin,
        title=title,
        filename=file.filename or "document.md",
        mime=file.content_type,
        data=data,
        ip=client_ip(request),
    )
    if error:
        return ok(payload, f"文档已保存，但切片失败：{error}")
    return ok(payload, "文档已上传并完成切片，请到切片列表建立索引")


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


@router.get("/chunk-sets")
async def list_chunk_sets(
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """切片列表：已切好但还没建立索引的文档及其切片参数。"""
    return ok(await kb_service.list_chunk_sets(db))


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
