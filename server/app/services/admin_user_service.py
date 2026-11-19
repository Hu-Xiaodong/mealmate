"""后台用户管理服务。

第一阶段只做三件事：查看用户列表与详情、封禁、解封。
封禁只改状态并撤销会话，不删除任何数据，保证可追溯、可恢复。
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import iso
from app.core.errors import AppError
from app.core.security import decrypt_phone, mask_phone
from app.db.models import Favorite, Like, MealPost, Session, User
from app.services.audit_service import write_audit
from app.utils.cursor import decode_cursor, encode_cursor
from app.utils.time import as_utc, now_utc

MAX_PAGE_SIZE = 50
# 关键词搜索时最多扫描的用户数。当前项目数据量小，这样实现最简单；
# 生产环境应在写入时保存手机号后四位或检索摘要，避免全表解密。
MAX_SEARCH_SCAN = 2000


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _user_payload(user: User, post_count: int = 0) -> dict[str, Any]:
    """后台用户摘要。

    手机号默认脱敏，列表里不返回完整号码。
    完整号码属于敏感个人信息，方案中要求额外的查看权限并写审计日志。
    """
    return {
        "id": user.id,
        "nickname": user.nickname,
        "phoneMasked": mask_phone(decrypt_phone(user.phone_encrypted)),
        "avatarUrl": user.avatar_url,
        "status": user.status,
        "postCount": post_count,
        "createdAt": iso(user.created_at),
    }


async def _post_counts(db: AsyncSession, user_ids: list[str]) -> dict[str, int]:
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(MealPost.author_id, func.count(MealPost.id))
            .where(MealPost.author_id.in_(user_ids))
            .group_by(MealPost.author_id)
        )
    ).all()
    return {author_id: int(count) for author_id, count in rows}


async def list_admin_users(
    db: AsyncSession,
    *,
    keyword: str | None,
    status: str | None,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    """用户列表，支持昵称或手机号后四位搜索。

    注意：手机号在数据库中是加密存储的，无法直接用 SQL 做后缀匹配，
    所以当前实现在有限范围内取出后解密过滤。生产环境应增加专用检索列。
    """
    limit = min(max(limit, 1), MAX_PAGE_SIZE)
    keyword_text = (keyword or "").strip()
    status_text = (status or "").strip()
    if status_text and status_text not in {"active", "disabled", "system"}:
        raise AppError("USER_STATUS_INVALID", "用户状态筛选值不正确")

    conditions = []
    if status_text:
        conditions.append(User.status == status_text)

    # 有关键词时先取一批候选再在内存中匹配，避免把解密逻辑写进 SQL。
    scan_limit = MAX_SEARCH_SCAN if keyword_text else limit + 1
    rows = (
        await db.scalars(
            select(User)
            .where(*conditions)
            .order_by(User.created_at.desc(), User.id.desc())
            .limit(scan_limit)
        )
    ).all()

    if keyword_text:
        lowered = keyword_text.lower()
        digits_only = keyword_text.isdigit()
        matched = []
        for user in rows:
            nickname_hit = lowered in user.nickname.lower()
            phone_hit = digits_only and decrypt_phone(user.phone_encrypted).endswith(
                keyword_text
            )
            if nickname_hit or phone_hit:
                matched.append(user)
        rows = matched

    cursor_data = decode_cursor(cursor)
    if cursor:
        created = _parse_dt(cursor_data.get("createdAt") if cursor_data else None)
        cursor_id = cursor_data.get("id") if cursor_data else None
        if created is None or not cursor_id:
            raise AppError("CURSOR_INVALID", "分页游标无效，请刷新后重试")
        rows = [
            user
            for user in rows
            if as_utc(user.created_at) < created
            or (as_utc(user.created_at) == created and user.id < cursor_id)
        ]

    has_more = len(rows) > limit
    page = rows[:limit]
    counts = await _post_counts(db, [user.id for user in page])
    items = [_user_payload(user, counts.get(user.id, 0)) for user in page]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor({"createdAt": last.created_at.isoformat(), "id": last.id})
    return {"items": items, "nextCursor": next_cursor, "hasMore": has_more}


async def get_admin_user(db: AsyncSession, user_id: str) -> dict[str, Any]:
    """用户详情：基础资料加发布数、点赞数、收藏数。"""
    user = await db.get(User, user_id)
    if user is None:
        raise AppError("USER_NOT_FOUND", "用户不存在", status_code=404)

    post_count = await db.scalar(
        select(func.count(MealPost.id)).where(MealPost.author_id == user.id)
    )
    like_count = await db.scalar(
        select(func.count(Like.id)).where(
            Like.account_id == user.id,
            Like.active.is_(True),
            Like.risk_status == "valid",
        )
    )
    favorite_count = await db.scalar(
        select(func.count(Favorite.id)).where(Favorite.account_id == user.id)
    )

    payload = _user_payload(user, int(post_count or 0))
    payload.update(
        {
            "likeCount": int(like_count or 0),
            "favoriteCount": int(favorite_count or 0),
        }
    )
    return payload


async def _require_user(db: AsyncSession, user_id: str) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise AppError("USER_NOT_FOUND", "用户不存在", status_code=404)
    return user


def _snapshot(user: User) -> dict[str, Any]:
    return {"status": user.status, "nickname": user.nickname}


async def ban_user(
    db: AsyncSession, admin, user_id: str, reason: str, ip: str | None
) -> dict[str, Any]:
    """封禁用户。

    只把状态改为 disabled，同时撤销该用户全部未注销会话。
    不删除用户、饭帖、点赞等数据，解封后可以恢复使用。
    如果只改状态不撤会话，用户手里的旧令牌在过期前仍然可以继续操作。
    """
    user = await _require_user(db, user_id)
    text = reason.strip()
    if len(text) < 2:
        raise AppError("REASON_REQUIRED", "请填写至少 2 个字的原因")
    if user.status == "system":
        raise AppError("USER_PROTECTED", "系统账号不能被封禁", status_code=409)
    if user.status == "disabled":
        return {"id": user.id, "status": user.status, "changed": False}

    before = _snapshot(user)
    user.status = "disabled"
    revoked = await db.execute(
        update(Session)
        .where(Session.account_id == user.id, Session.revoked_at.is_(None))
        .values(revoked_at=now_utc())
    )
    write_audit(
        db,
        actor=admin,
        action="user.ban",
        target_type="user",
        target_id=user.id,
        reason=text[:200],
        before=before,
        after={**_snapshot(user), "revokedSessions": int(revoked.rowcount or 0)},
        ip=ip,
    )
    await db.commit()
    return {"id": user.id, "status": user.status, "changed": True}


async def unban_user(
    db: AsyncSession, admin, user_id: str, ip: str | None
) -> dict[str, Any]:
    """解封用户：disabled -> active。已正常使用的账号重复解封直接返回当前状态。"""
    user = await _require_user(db, user_id)
    if user.status == "system":
        raise AppError("USER_PROTECTED", "系统账号不能通过这里修改", status_code=409)
    if user.status == "active":
        return {"id": user.id, "status": user.status, "changed": False}

    before = _snapshot(user)
    user.status = "active"
    write_audit(
        db,
        actor=admin,
        action="user.unban",
        target_type="user",
        target_id=user.id,
        before=before,
        after=_snapshot(user),
        ip=ip,
    )
    await db.commit()
    return {"id": user.id, "status": user.status, "changed": True}
