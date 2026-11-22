"""管理后台认证服务。

与普通用户认证完全独立：
- 账号来自 admin_users，不使用手机号；
- 密码使用 Argon2id 哈希校验；
- 会话来自 admin_sessions，默认 1 天（1440 分钟）过期；
- 登录失败按“用户名 + 来源地址”计数并锁定。
"""

import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import iso
from app.core.config import settings
from app.core.errors import AppError
from app.core.security import (
    admin_token_digest,
    hash_password,
    issue_session_token,
    new_id,
    read_session_token,
    verify_password,
)
from app.db.models import (
    AdminLoginAttempt,
    AdminRolePermission,
    AdminSession,
    AdminUser,
    AdminUserRole,
)
from app.utils.time import as_utc, now_utc

# 用户名不存在时也执行一次真实的哈希校验，让响应时间接近，
# 避免攻击者通过“响应快慢”判断哪些用户名存在。
_DUMMY_PASSWORD_HASH = hash_password("timing-placeholder-not-a-real-account")


@dataclass
class AdminAuthResult:
    """登录成功后返回给路由层的数据集合。"""

    admin: AdminUser
    token: str
    expires_at: datetime
    permissions: list[str]


async def admin_permissions(db: AsyncSession, admin_id: str) -> list[str]:
    """查询某个管理员的全部权限点。

    管理员可以有多个角色，权限取所有角色权限点的并集并去重。
    返回排序后的列表，方便前端稳定展示和测试断言。
    """
    rows = await db.scalars(
        select(AdminRolePermission.permission_code)
        .join(AdminUserRole, AdminUserRole.role_id == AdminRolePermission.role_id)
        .where(AdminUserRole.admin_id == admin_id)
        .distinct()
    )
    return sorted(set(rows.all()))


async def login_admin(
    db: AsyncSession, *, username: str, password: str, ip: str | None
) -> AdminAuthResult:
    """校验用户名密码并签发管理员会话。

    Args:
        db: 数据库会话。
        username: 登录名，前后空格会被去除。
        password: 明文密码，只在内存中参与哈希校验。
        ip: 来源地址，用于登录失败计数和审计。
    Returns:
        AdminAuthResult，包含令牌、过期时间、管理员信息和权限点。
    Raises:
        AppError: 用户名密码错误返回 401；账号停用返回 403；
            失败次数超限返回 423 并附带剩余秒数。
    Why:
        登录是后台的第一道边界，必须同时处理密码校验、失败锁定和会话签发，
        不能把这些逻辑散落在路由函数里。
    """
    normalized = username.strip()
    now = now_utc()
    attempt = await db.scalar(
        select(AdminLoginAttempt).where(
            AdminLoginAttempt.username == normalized,
            AdminLoginAttempt.ip == (ip or "unknown"),
        )
    )

    # 先检查锁定状态：锁定期间即使密码正确也不允许登录。
    if attempt and attempt.locked_until is not None:
        locked_until = as_utc(attempt.locked_until)
        if locked_until > now:
            retry_after = max(int((locked_until - now).total_seconds()), 1)
            raise AppError(
                "ADMIN_LOGIN_LOCKED",
                f"登录失败次数过多，请 {max(retry_after // 60, 1)} 分钟后再试",
                status_code=423,
                data={"retryAfter": retry_after},
                headers={"Retry-After": str(retry_after)},
            )

    admin = await db.scalar(select(AdminUser).where(AdminUser.username == normalized))
    password_ok = verify_password(
        admin.password_hash if admin else _DUMMY_PASSWORD_HASH, password
    )

    if admin is None or not password_ok:
        remaining, retry_after = await _record_failure(db, normalized, ip, attempt, now)
        if retry_after is not None:
            raise AppError(
                "ADMIN_LOGIN_LOCKED",
                f"登录失败次数过多，请 {settings.admin_lock_minutes} 分钟后再试",
                status_code=423,
                data={"retryAfter": retry_after},
                headers={"Retry-After": str(retry_after)},
            )
        raise AppError(
            "ADMIN_LOGIN_FAILED",
            "用户名或密码不正确",
            status_code=401,
            data={"remainingAttempts": remaining},
        )

    if admin.status != "active":
        raise AppError("ADMIN_DISABLED", "该管理员账号已停用", status_code=403)

    # 登录成功：清空失败计数，记录最后登录时间，签发新会话。
    if attempt is not None:
        await db.delete(attempt)
    admin.last_login_at = now
    # 与用户端一致：先生成会话编号，再加密成令牌返回，数据库只存摘要。
    session_id = new_id("as")
    token, payload = issue_session_token(session_id, prefix="adm_")
    expires_at = now + timedelta(minutes=settings.admin_session_ttl_minutes)
    db.add(
        AdminSession(
            id=session_id,
            admin_id=admin.id,
            token_digest=admin_token_digest(payload),
            expires_at=expires_at,
            ip=ip,
        )
    )
    await db.commit()
    await db.refresh(admin)
    permissions = await admin_permissions(db, admin.id)
    return AdminAuthResult(
        admin=admin, token=token, expires_at=expires_at, permissions=permissions
    )


async def _record_failure(
    db: AsyncSession,
    username: str,
    ip: str | None,
    attempt: AdminLoginAttempt | None,
    now: datetime,
) -> tuple[int, int | None]:
    """记录一次登录失败并判断是否触发锁定。

    Returns:
        (剩余尝试次数, 锁定剩余秒数)。未触发锁定时第二项为 None。
    Why:
        计数必须落库。只放内存的话，服务重启或多实例部署会让限制失效。
    """
    if attempt is None:
        attempt = AdminLoginAttempt(
            id=new_id("ala"),
            username=username,
            ip=ip or "unknown",
            failed_count=0,
            window_started_at=now,
        )
        db.add(attempt)

    window = timedelta(minutes=settings.admin_login_window_minutes)
    if now - as_utc(attempt.window_started_at) > window:
        # 超出统计窗口，开始新一轮计数。
        attempt.failed_count = 1
        attempt.window_started_at = now
        attempt.locked_until = None
    else:
        attempt.failed_count += 1

    retry_after: int | None = None
    if attempt.failed_count >= settings.admin_login_max_attempts:
        attempt.locked_until = now + timedelta(minutes=settings.admin_lock_minutes)
        retry_after = settings.admin_lock_minutes * 60

    await db.commit()
    remaining = max(settings.admin_login_max_attempts - attempt.failed_count, 0)
    return remaining, retry_after


async def resolve_admin_session(db: AsyncSession, token: str) -> AdminUser | None:
    """根据令牌解析当前管理员。

    令牌先解密得到会话编号，再读取会话并比对摘要。
    会话过期、已注销、账号停用三种情况都返回 None，由接口层统一返回 401。
    """
    parsed = read_session_token(token, prefix="adm_")
    if parsed is None:
        return None
    session_id, payload = parsed
    session = await db.get(AdminSession, session_id)
    if session is None or session.revoked_at is not None:
        return None
    if not hmac.compare_digest(session.token_digest, admin_token_digest(payload)):
        return None
    if as_utc(session.expires_at) < now_utc():
        return None
    admin = await db.get(AdminUser, session.admin_id)
    if admin is None or admin.status != "active":
        return None
    return admin


async def revoke_admin_session(db: AsyncSession, token: str) -> None:
    """注销当前管理员会话。

    不删除会话行，而是写入 revoked_at。保留记录便于审计“谁在什么时候退出”。
    """
    parsed = read_session_token(token, prefix="adm_")
    if parsed is None:
        return
    session_id, payload = parsed
    session = await db.get(AdminSession, session_id)
    if (
        session is not None
        and session.revoked_at is None
        and hmac.compare_digest(session.token_digest, admin_token_digest(payload))
    ):
        session.revoked_at = now_utc()
        await db.commit()


def admin_payload(admin: AdminUser) -> dict:
    """输出给前端的管理员公开信息，不包含密码哈希。"""
    return {
        "id": admin.id,
        "username": admin.username,
        "displayName": admin.display_name,
        "status": admin.status,
        "lastLoginAt": iso(admin.last_login_at),
        "createdAt": iso(admin.created_at),
    }
