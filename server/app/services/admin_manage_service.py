"""管理员与角色管理。

设计原则：
1. 管理员与普通用户完全隔离，复用独立表 admin_users；
2. 权限不直接挂在账号上，而是先定义角色，再把角色分配给管理员；
3. 所有写操作都落审计日志；
4. 系统保护超级管理员角色，避免误操作把后台锁死。
"""

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import iso
from app.core.errors import AppError
from app.core.permissions import ALL_PERMISSIONS, permission_payload
from app.core.security import hash_password, new_id
from app.db.models import (
    AdminRole,
    AdminRolePermission,
    AdminUser,
    AdminUserRole,
)
from app.schemas import (
    AdminCreateRequest,
    AdminRoleRequest,
    AdminRoleUpdateRequest,
    AdminUpdateRequest,
)
from app.services.audit_service import write_audit
from app.utils.time import now_utc

BUILTIN_ROLES = {"super_admin", "content_operator", "ai_operator", "auditor"}
SUPER_ROLE = "super_admin"


def _admin_payload(admin: AdminUser, roles: list[AdminRole]) -> dict[str, Any]:
    return {
        "id": admin.id,
        "username": admin.username,
        "displayName": admin.display_name,
        "status": admin.status,
        "lastLoginAt": iso(admin.last_login_at),
        "createdAt": iso(admin.created_at),
        "roles": [{"id": role.id, "code": role.code, "name": role.name} for role in roles],
    }


def _role_payload(
    role: AdminRole, permissions: list[str], admin_count: int = 0
) -> dict[str, Any]:
    return {
        "id": role.id,
        "code": role.code,
        "name": role.name,
        "permissions": permissions,
        "adminCount": admin_count,
        "builtin": role.code in BUILTIN_ROLES,
    }


async def _roles_for_admins(db: AsyncSession, admin_ids: list[str]) -> dict[str, list[AdminRole]]:
    if not admin_ids:
        return {}
    rows = (
        await db.execute(
            select(AdminUserRole.admin_id, AdminRole)
            .join(AdminRole, AdminRole.id == AdminUserRole.role_id)
            .where(AdminUserRole.admin_id.in_(admin_ids))
            .order_by(AdminRole.code)
        )
    ).all()
    result: dict[str, list[AdminRole]] = {admin_id: [] for admin_id in admin_ids}
    for admin_id, role in rows:
        result.setdefault(admin_id, []).append(role)
    return result


async def list_admins(
    db: AsyncSession,
    *,
    keyword: str | None,
    status: str | None,
) -> dict[str, Any]:
    conditions = []
    if keyword and keyword.strip():
        text = keyword.strip()
        conditions.append(
            AdminUser.username.contains(text) | AdminUser.display_name.contains(text)
        )
    if status and status.strip():
        if status not in {"active", "disabled"}:
            raise AppError("ADMIN_STATUS_INVALID", "管理员状态筛选值不正确")
        conditions.append(AdminUser.status == status)

    rows = (
        await db.scalars(
            select(AdminUser).where(*conditions).order_by(AdminUser.created_at.desc())
        )
    ).all()
    role_map = await _roles_for_admins(db, [admin.id for admin in rows])
    return {"items": [_admin_payload(admin, role_map.get(admin.id, [])) for admin in rows]}


async def list_roles(db: AsyncSession) -> dict[str, Any]:
    roles = (await db.scalars(select(AdminRole).order_by(AdminRole.code))).all()
    permission_map: dict[str, list[str]] = {}
    rows = (
        await db.execute(
            select(AdminRolePermission.role_id, AdminRolePermission.permission_code)
            .order_by(AdminRolePermission.permission_code)
        )
    ).all()
    for role_id, code in rows:
        permission_map.setdefault(role_id, []).append(code)

    counts = dict(
        (
            await db.execute(
                select(AdminUserRole.role_id, func.count(AdminUserRole.id)).group_by(
                    AdminUserRole.role_id
                )
            )
        ).all()
    )
    return {
        "items": [
            _role_payload(role, permission_map.get(role.id, []), int(counts.get(role.id, 0)))
            for role in roles
        ],
        "permissions": permission_payload(),
    }


async def _require_admin(db: AsyncSession, admin_id: str) -> AdminUser:
    admin = await db.get(AdminUser, admin_id)
    if admin is None:
        raise AppError("ADMIN_NOT_FOUND", "管理员不存在", status_code=404)
    return admin


async def _roles_by_ids(db: AsyncSession, role_ids: list[str]) -> list[AdminRole]:
    if not role_ids:
        return []
    roles = (
        await db.scalars(select(AdminRole).where(AdminRole.id.in_(role_ids)))
    ).all()
    if len(roles) != len(set(role_ids)):
        raise AppError("ADMIN_ROLE_INVALID", "包含不存在的角色", status_code=400)
    return list(roles)


async def _replace_admin_roles(
    db: AsyncSession, admin_id: str, role_ids: list[str]
) -> None:
    await db.execute(delete(AdminUserRole).where(AdminUserRole.admin_id == admin_id))
    for role_id in dict.fromkeys(role_ids):
        db.add(AdminUserRole(id=new_id("aur"), admin_id=admin_id, role_id=role_id))


async def _permission_codes_for_roles(db: AsyncSession, role_ids: list[str]) -> set[str]:
    if not role_ids:
        return set()
    return set(
        (
            await db.scalars(
                select(AdminRolePermission.permission_code).where(
                    AdminRolePermission.role_id.in_(role_ids)
                )
            )
        ).all()
    )


def _admin_snapshot(admin: AdminUser, role_ids: list[str]) -> dict[str, Any]:
    return {
        "username": admin.username,
        "displayName": admin.display_name,
        "status": admin.status,
        "roleIds": role_ids,
    }


async def create_admin(
    db: AsyncSession,
    actor: AdminUser,
    body: AdminCreateRequest,
    ip: str | None,
) -> dict[str, Any]:
    existing = await db.scalar(
        select(AdminUser).where(AdminUser.username == body.username)
    )
    if existing is not None:
        raise AppError("ADMIN_USERNAME_EXISTS", "该登录名已存在", status_code=409)
    roles = await _roles_by_ids(db, body.role_ids)
    admin = AdminUser(
        id=new_id("adm"),
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name.strip(),
        status="active",
        created_at=now_utc(),
    )
    db.add(admin)
    await db.flush()
    await _replace_admin_roles(db, admin.id, [role.id for role in roles])
    write_audit(
        db,
        actor=actor,
        action="admin.create",
        target_type="admin",
        target_id=admin.id,
        after=_admin_snapshot(admin, [role.id for role in roles]),
        ip=ip,
    )
    await db.commit()
    return _admin_payload(admin, roles)


async def update_admin(
    db: AsyncSession,
    actor: AdminUser,
    admin_id: str,
    body: AdminUpdateRequest,
    ip: str | None,
) -> dict[str, Any]:
    admin = await _require_admin(db, admin_id)
    current_roles = (await _roles_for_admins(db, [admin_id])).get(admin_id, [])
    before = _admin_snapshot(admin, [role.id for role in current_roles])

    if admin.id == actor.id and body.status == "disabled":
        raise AppError("ADMIN_SELF_PROTECTED", "不能停用当前登录的账号", status_code=409)

    roles = current_roles
    if body.role_ids is not None:
        roles = await _roles_by_ids(db, body.role_ids)
        if admin.id == actor.id:
            permissions = await _permission_codes_for_roles(
                db, [role.id for role in roles]
            )
            if "admin.manage" not in permissions:
                raise AppError(
                    "ADMIN_SELF_PROTECTED",
                    "不能移除自己的管理员管理权限",
                    status_code=409,
                )
        await _replace_admin_roles(db, admin.id, [role.id for role in roles])

    if body.display_name is not None:
        admin.display_name = body.display_name.strip()
    if body.password is not None:
        admin.password_hash = hash_password(body.password)
    if body.status is not None:
        admin.status = body.status

    write_audit(
        db,
        actor=actor,
        action="admin.update",
        target_type="admin",
        target_id=admin.id,
        before=before,
        after=_admin_snapshot(admin, [role.id for role in roles]),
        ip=ip,
    )
    await db.commit()
    return _admin_payload(admin, roles)


async def create_role(
    db: AsyncSession,
    actor: AdminUser,
    body: AdminRoleRequest,
    ip: str | None,
) -> dict[str, Any]:
    if await db.scalar(select(AdminRole).where(AdminRole.code == body.code)) is not None:
        raise AppError("ADMIN_ROLE_EXISTS", "该角色编码已存在", status_code=409)
    invalid = set(body.permissions) - set(ALL_PERMISSIONS)
    if invalid:
        raise AppError(
            "ADMIN_PERMISSION_UNKNOWN",
            "包含未知权限点",
            status_code=400,
            data={"permissions": sorted(invalid)},
        )
    role = AdminRole(id=new_id("role"), code=body.code, name=body.name.strip())
    db.add(role)
    await db.flush()
    for code in dict.fromkeys(body.permissions):
        db.add(
            AdminRolePermission(
                id=new_id("arp"), role_id=role.id, permission_code=code
            )
        )
    write_audit(
        db,
        actor=actor,
        action="admin_role.create",
        target_type="admin_role",
        target_id=role.id,
        after={"code": role.code, "name": role.name, "permissions": body.permissions},
        ip=ip,
    )
    await db.commit()
    return _role_payload(role, body.permissions)


async def update_role(
    db: AsyncSession,
    actor: AdminUser,
    role_id: str,
    body: AdminRoleUpdateRequest,
    ip: str | None,
) -> dict[str, Any]:
    role = await db.get(AdminRole, role_id)
    if role is None:
        raise AppError("ADMIN_ROLE_NOT_FOUND", "角色不存在", status_code=404)

    current = list(
        (
            await db.scalars(
                select(AdminRolePermission.permission_code).where(
                    AdminRolePermission.role_id == role.id
                )
            )
        ).all()
    )
    before = {"code": role.code, "name": role.name, "permissions": current}

    if body.name is not None:
        role.name = body.name.strip()

    if body.permissions is not None:
        # 超级管理员角色永远保留全部权限，避免误删后无人能进入后台。
        permissions = (
            list(ALL_PERMISSIONS) if role.code == SUPER_ROLE else body.permissions
        )
        invalid = set(permissions) - set(ALL_PERMISSIONS)
        if invalid:
            raise AppError(
                "ADMIN_PERMISSION_UNKNOWN",
                "包含未知权限点",
                status_code=400,
                data={"permissions": sorted(invalid)},
            )
        await db.execute(
            delete(AdminRolePermission).where(AdminRolePermission.role_id == role.id)
        )
        for code in dict.fromkeys(permissions):
            db.add(
                AdminRolePermission(
                    id=new_id("arp"), role_id=role.id, permission_code=code
                )
            )
        current = list(dict.fromkeys(permissions))

    write_audit(
        db,
        actor=actor,
        action="admin_role.update",
        target_type="admin_role",
        target_id=role.id,
        before=before,
        after={"code": role.code, "name": role.name, "permissions": current},
        ip=ip,
    )
    await db.commit()
    admin_count = int(
        await db.scalar(
            select(func.count(AdminUserRole.id)).where(AdminUserRole.role_id == role.id)
        )
        or 0
    )
    return _role_payload(role, current, admin_count)


async def delete_role(
    db: AsyncSession, actor: AdminUser, role_id: str, ip: str | None
) -> dict[str, Any]:
    role = await db.get(AdminRole, role_id)
    if role is None:
        raise AppError("ADMIN_ROLE_NOT_FOUND", "角色不存在", status_code=404)
    if role.code in BUILTIN_ROLES:
        raise AppError("ADMIN_ROLE_PROTECTED", "内置角色不能删除", status_code=409)
    assigned = int(
        await db.scalar(
            select(func.count(AdminUserRole.id)).where(AdminUserRole.role_id == role.id)
        )
        or 0
    )
    if assigned > 0:
        raise AppError(
            "ADMIN_ROLE_IN_USE",
            f"该角色仍分配给 {assigned} 个管理员，请先解除分配",
            status_code=409,
        )
    await db.execute(delete(AdminRolePermission).where(AdminRolePermission.role_id == role.id))
    await db.execute(delete(AdminRole).where(AdminRole.id == role.id))
    write_audit(
        db,
        actor=actor,
        action="admin_role.delete",
        target_type="admin_role",
        target_id=role.id,
        before={"code": role.code, "name": role.name},
        ip=ip,
    )
    await db.commit()
    return {"id": role.id, "deleted": True}
