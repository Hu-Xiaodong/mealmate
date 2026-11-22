from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import AdminPrincipal, client_ip, require_permission
from app.core.responses import ok
from app.db.session import get_db
from app.schemas import (
    AdminCreateRequest,
    AdminRoleRequest,
    AdminRoleUpdateRequest,
    AdminUpdateRequest,
)
from app.services.admin_manage_service import (
    create_admin,
    create_role,
    delete_role,
    list_admins,
    list_roles,
    update_admin,
    update_role,
)

router = APIRouter(prefix="/admin", tags=["admin-manage"])


@router.get("/admins")
async def admins(
    keyword: str | None = Query(default=None, max_length=40),
    status_filter: str | None = Query(default=None, alias="status"),
    principal: AdminPrincipal = Depends(require_permission("admin.manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await list_admins(db, keyword=keyword, status=status_filter))


@router.post("/admins")
async def add_admin(
    body: AdminCreateRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("admin.manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(
        await create_admin(db, principal.admin, body, client_ip(request)),
        "管理员已创建",
    )


@router.put("/admins/{admin_id}")
async def edit_admin(
    admin_id: str,
    body: AdminUpdateRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("admin.manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(
        await update_admin(db, principal.admin, admin_id, body, client_ip(request)),
        "管理员已保存",
    )


@router.get("/roles")
async def roles(
    principal: AdminPrincipal = Depends(require_permission("admin.manage")),
    db: AsyncSession = Depends(get_db),
):
    """角色列表，同时返回系统支持的权限点目录，供前端渲染多选框。"""
    return ok(await list_roles(db))


@router.post("/roles")
async def add_role(
    body: AdminRoleRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("admin.manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(
        await create_role(db, principal.admin, body, client_ip(request)),
        "角色已创建",
    )


@router.put("/roles/{role_id}")
async def edit_role(
    role_id: str,
    body: AdminRoleUpdateRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("admin.manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(
        await update_role(db, principal.admin, role_id, body, client_ip(request)),
        "角色已保存",
    )


@router.delete("/roles/{role_id}")
async def remove_role(
    role_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("admin.manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(
        await delete_role(db, principal.admin, role_id, client_ip(request)),
        "角色已删除",
    )
