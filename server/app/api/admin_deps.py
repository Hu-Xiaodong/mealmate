"""管理后台鉴权依赖。

FastAPI 的依赖注入让“取当前管理员”和“校验权限点”可以复用：
- get_current_admin：解析 Authorization 头，确认会话有效；
- require_permission("post.review")：在会话有效的基础上再检查权限点。

权限校验必须在服务端完成。前端隐藏按钮只是体验优化，
任何人手工构造请求都应该被这里拦住。
"""

from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import AdminUser
from app.db.session import get_db
from app.services.admin_auth_service import admin_permissions, resolve_admin_session


@dataclass
class AdminPrincipal:
    """当前登录管理员及其权限点集合。

    一次请求只查询一次权限，后续多个依赖复用同一个对象，避免重复查库。
    """

    admin: AdminUser
    permissions: list[str]


def admin_bearer_token(request: Request) -> str | None:
    """从 Authorization 请求头取出管理员令牌。"""
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AppError("ADMIN_SESSION_INVALID", "管理后台登录状态无效", status_code=401)
    return token.strip()


def client_ip(request: Request) -> str:
    """获取来源地址，用于登录失败计数和审计日志。

    部署在 Nginx 等反向代理之后时，真实地址在 X-Forwarded-For 的第一段。
    如果服务直接暴露公网，这个头可以被伪造，所以生产环境应只信任代理写入的值。
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64] or "unknown"
    return (request.client.host if request.client else "unknown")[:64]


async def get_current_admin(
    request: Request, db: AsyncSession = Depends(get_db)
) -> AdminPrincipal:
    """解析当前管理员并加载权限点，未登录或会话失效返回 401。"""
    token = admin_bearer_token(request)
    if not token:
        raise AppError("ADMIN_UNAUTHENTICATED", "请先登录管理后台", status_code=401)
    admin = await resolve_admin_session(db, token)
    if admin is None:
        raise AppError("ADMIN_SESSION_INVALID", "管理后台登录已失效，请重新登录", status_code=401)
    permissions = await admin_permissions(db, admin.id)
    return AdminPrincipal(admin=admin, permissions=permissions)


def require_permission(permission_code: str):
    """生成一个校验指定权限点的依赖。

    Args:
        permission_code: 例如 post.review、user.ban、audit.read。
    Returns:
        可传给 Depends 的函数；没有权限时抛出 403。
    Why:
        把权限声明写在路由参数上，接口和所需权限在同一个位置，
        新增接口时不容易漏掉校验。
    """

    async def dependency(
        principal: AdminPrincipal = Depends(get_current_admin),
    ) -> AdminPrincipal:
        if permission_code not in principal.permissions:
            raise AppError(
                "ADMIN_PERMISSION_DENIED",
                "当前账号没有该操作权限",
                status_code=403,
                data={"requiredPermission": permission_code},
            )
        return principal

    return dependency
