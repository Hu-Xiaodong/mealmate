from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import AdminPrincipal, client_ip, require_permission
from app.core.responses import ok
from app.db.session import get_db
from app.schemas import TasteTagCreateRequest, TasteTagUpdateRequest
from app.services.admin_taste_tag_service import (
    create_tag,
    delete_tag,
    list_tags,
    update_tag,
)

router = APIRouter(prefix="/admin/taste-tags", tags=["admin-taste-tags"])


@router.get("")
async def list_dict(
    principal: AdminPrincipal = Depends(require_permission("taste_tag.manage")),
    db: AsyncSession = Depends(get_db),
):
    """完整字典（含停用标签）及每个标签的使用量。"""
    return ok(await list_tags(db))


@router.post("")
async def create(
    body: TasteTagCreateRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("taste_tag.manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(
        await create_tag(db, principal.admin, body, client_ip(request)),
        "标签已新增",
    )


@router.put("/{name}")
async def update(
    name: str,
    body: TasteTagUpdateRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("taste_tag.manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(
        await update_tag(db, principal.admin, name, body, client_ip(request)),
        "标签已保存",
    )


@router.delete("/{name}")
async def remove(
    name: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("taste_tag.manage")),
    db: AsyncSession = Depends(get_db),
):
    """删除从未被使用的标签；已被引用时返回 409，提示改为停用。"""
    return ok(
        await delete_tag(db, principal.admin, name, client_ip(request)),
        "标签已删除",
    )
