from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import (
    AdminPrincipal,
    admin_bearer_token,
    client_ip,
    get_current_admin,
)
from app.api.serializers import iso
from app.core.errors import AppError
from app.core.responses import ok
from app.db.session import get_db
from app.schemas import AdminLoginRequest
from app.services.admin_auth_service import (
    admin_payload,
    login_admin,
    revoke_admin_session,
)

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


@router.post("/login")
async def login(
    body: AdminLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """管理员登录：用户名 + 密码，返回令牌和权限点列表。

    前端拿到 permissions 后只用来决定菜单和按钮是否显示；
    真正的权限判断仍然由每个后台接口在服务端完成。
    """
    result = await login_admin(
        db,
        username=body.username,
        password=body.password,
        ip=client_ip(request),
    )
    return ok(
        {
            "token": result.token,
            "tokenType": "Bearer",
            "expiresAt": iso(result.expires_at),
            "admin": admin_payload(result.admin),
            "permissions": result.permissions,
        },
        "登录成功",
    )


@router.get("/me")
async def me(principal: AdminPrincipal = Depends(get_current_admin)):
    """返回当前管理员信息与权限点，用于刷新页面后恢复登录态。"""
    return ok(
        {
            "admin": admin_payload(principal.admin),
            "permissions": principal.permissions,
        }
    )


@router.post("/logout")
async def logout(
    request: Request,
    principal: AdminPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """注销当前管理员会话，令牌立即失效。"""
    token = admin_bearer_token(request)
    if not token:
        raise AppError("ADMIN_SESSION_INVALID", "管理后台登录状态无效", status_code=401)
    await revoke_admin_session(db, token)
    return ok({"revoked": True}, "已退出登录")
