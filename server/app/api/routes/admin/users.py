from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import AdminPrincipal, client_ip, require_permission
from app.core.responses import ok
from app.db.session import get_db
from app.schemas import ReasonRequest
from app.services.admin_user_service import (
    ban_user,
    get_admin_user,
    list_admin_users,
    unban_user,
)

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


@router.get("")
async def list_users(
    keyword: str | None = Query(default=None, max_length=40),
    status_filter: str | None = Query(default=None, alias="status"),
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    principal: AdminPrincipal = Depends(require_permission("user.read")),
    db: AsyncSession = Depends(get_db),
):
    """用户列表，支持昵称或手机号后四位搜索。手机号默认脱敏。"""
    return ok(
        await list_admin_users(
            db,
            keyword=keyword,
            status=status_filter,
            cursor=cursor,
            limit=limit,
        )
    )


@router.get("/{user_id}")
async def user_detail(
    user_id: str,
    principal: AdminPrincipal = Depends(require_permission("user.read")),
    db: AsyncSession = Depends(get_db),
):
    """用户详情：基础资料、发布数、点赞数、收藏数。"""
    return ok(await get_admin_user(db, user_id))


@router.post("/{user_id}/ban")
async def ban(
    user_id: str,
    body: ReasonRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("user.ban")),
    db: AsyncSession = Depends(get_db),
):
    """封禁用户，同时撤销其全部会话。"""
    data = await ban_user(
        db, principal.admin, user_id, body.reason, client_ip(request)
    )
    return ok(data, "已封禁" if data["changed"] else "该用户已被封禁")


@router.post("/{user_id}/unban")
async def unban(
    user_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("user.ban")),
    db: AsyncSession = Depends(get_db),
):
    """解封用户。"""
    data = await unban_user(db, principal.admin, user_id, client_ip(request))
    return ok(data, "已解封" if data["changed"] else "该用户当前可正常使用")
