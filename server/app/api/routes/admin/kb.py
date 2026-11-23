"""知识库后台接口。

接口分为三组：
1. 文档：上传、列表、详情、重建索引、删除、查看切片；
2. 索引版本：列表、新建、启用；
3. 检索测试：用真实问题验证召回效果。

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
    """上传 Markdown 或纯文本文档，上传后立即切片并生成向量。

    索引失败仍返回 200，但在 message 与文档状态中说明原因：
    文件已经保存，运营修复模型配置后可以直接重建，不需要重新上传。
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
        return ok(payload, f"文档已保存，但索引失败：{error}")
    return ok(payload, "文档已上传并完成索引")


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await kb_service.get_document(db, document_id))


@router.post("/documents/{document_id}/reindex")
async def reindex_document(
    document_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("kb.document.manage")),
    db: AsyncSession = Depends(get_db),
):
    """按当前启用版本重新切片、重新嵌入。"""
    payload, error = await kb_service.reindex_document(
        db, principal.admin, document_id, client_ip(request)
    )
    if error:
        return ok(payload, f"重建失败：{error}")
    return ok(payload, "已按当前索引版本重建完成")


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
