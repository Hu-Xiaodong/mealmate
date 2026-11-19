"""饭帖审核服务。

审核是一个明确的状态机，只允许三条路径：
    pending_review -> published   （通过）
    pending_review -> rejected    （拒绝）
    published      -> unpublished （下架）

其他组合一律拒绝。重复点击同一个操作时返回当前状态而不是报错，
这样前端网络重试、用户连点都不会产生重复写入。
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import authors_map, iso, media_map
from app.core.errors import AppError
from app.core.security import decrypt_phone, mask_phone
from app.db.models import AdminUser, MealPost, Recipe, User
from app.services.audit_service import write_audit
from app.services.cache import delete_key
from app.utils.cursor import decode_cursor, encode_cursor
from app.utils.time import business_date, now_utc

POST_STATUSES = {"pending_review", "published", "rejected", "unpublished"}
MAX_PAGE_SIZE = 50


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _snapshot(post: MealPost) -> dict[str, Any]:
    """记录饭帖审核相关字段的快照，用于审计日志的前后对比。"""
    return {
        "status": post.status,
        "reviewedBy": post.reviewed_by,
        "reviewedAt": iso(post.reviewed_at),
        "reviewReason": post.review_reason,
        "publishedAt": iso(post.published_at),
    }


async def _reviewer_names(db: AsyncSession, posts: list[MealPost]) -> dict[str, str]:
    """批量查询审核人显示名，避免列表逐行查询造成 N+1 问题。"""
    ids = {post.reviewed_by for post in posts if post.reviewed_by}
    if not ids:
        return {}
    rows = (await db.scalars(select(AdminUser).where(AdminUser.id.in_(ids)))).all()
    return {admin.id: admin.display_name or admin.username for admin in rows}


def _post_payload(
    post: MealPost,
    author: User | None,
    images: list[str],
    reviewer_name: str | None,
) -> dict[str, Any]:
    """后台列表使用的饭帖摘要。

    与面向用户的卡片不同，后台需要状态、审核原因、审核人等治理字段。
    """
    return {
        "id": post.id,
        "title": post.title,
        "review": post.review,
        "source": post.source,
        "coverImage": images[0] if images else None,
        "images": images,
        "imageCount": len(images),
        "author": (
            {
                "id": author.id,
                "nickname": author.nickname,
                "avatarUrl": author.avatar_url,
            }
            if author
            else None
        ),
        "status": post.status,
        "reviewReason": post.review_reason,
        "reviewedAt": iso(post.reviewed_at),
        "reviewedByName": reviewer_name,
        "createdAt": iso(post.created_at),
        "publishedAt": iso(post.published_at),
    }


async def list_admin_posts(
    db: AsyncSession,
    *,
    status: str | None,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    """后台饭帖列表，支持按状态筛选和游标分页。

    默认按创建时间倒序：新提交的内容排在前面，审核人员先处理最新的。
    """
    if status and status not in POST_STATUSES:
        raise AppError("POST_STATUS_INVALID", "饭帖状态筛选值不正确")

    limit = min(max(limit, 1), MAX_PAGE_SIZE)
    conditions = []
    if status:
        conditions.append(MealPost.status == status)

    cursor_data = decode_cursor(cursor)
    if cursor:
        created = _parse_dt(cursor_data.get("createdAt") if cursor_data else None)
        cursor_id = cursor_data.get("id") if cursor_data else None
        if created is None or not cursor_id:
            raise AppError("CURSOR_INVALID", "分页游标无效，请刷新后重试")
        conditions.append(
            or_(
                MealPost.created_at < created,
                and_(MealPost.created_at == created, MealPost.id < cursor_id),
            )
        )

    rows = (
        await db.scalars(
            select(MealPost)
            .where(*conditions)
            .order_by(MealPost.created_at.desc(), MealPost.id.desc())
            .limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    page = rows[:limit]

    authors = await authors_map(db, page)
    images = await media_map(db, page)
    reviewers = await _reviewer_names(db, page)

    items = [
        _post_payload(
            post,
            authors.get(post.author_id),
            images.get(post.id, []),
            reviewers.get(post.reviewed_by or ""),
        )
        for post in page
    ]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor({"createdAt": last.created_at.isoformat(), "id": last.id})
    return {"items": items, "nextCursor": next_cursor, "hasMore": has_more}


async def get_admin_post(db: AsyncSession, post_id: str) -> dict[str, Any]:
    """后台饭帖详情，包含作者、图片、来源、定位和审核记录。"""
    post = await db.get(MealPost, post_id)
    if post is None:
        raise AppError("POST_NOT_FOUND", "饭帖不存在", status_code=404)

    author = await db.get(User, post.author_id)
    images = await media_map(db, [post])
    reviewer = await db.get(AdminUser, post.reviewed_by) if post.reviewed_by else None
    payload = _post_payload(
        post,
        author,
        images.get(post.id, []),
        (reviewer.display_name or reviewer.username) if reviewer else None,
    )
    payload.update(
        {
            "authorRecipe": post.author_recipe,
            "authorPhoneMasked": (
                mask_phone(decrypt_phone(author.phone_encrypted)) if author else None
            ),
            "takeawayStore": post.takeaway_store,
            "dineInAddress": post.dine_in_address,
            "coarseArea": post.coarse_area,
            "coarseLat": post.coarse_lat,
            "coarseLng": post.coarse_lng,
            "clientRequestId": post.client_request_id,
            "platformRecipeId": post.platform_recipe_id,
            "platformRecipeTitle": None,
        }
    )
    if post.platform_recipe_id:
        recipe = await db.get(Recipe, post.platform_recipe_id)
        payload["platformRecipeTitle"] = recipe.title if recipe else None
    return payload


async def _require_post(db: AsyncSession, post_id: str) -> MealPost:
    """读取待变更的饭帖，并对该行加排他锁。

    Why:
        两个管理员同时点“通过”时，如果都先读到 pending_review 再写，
        会产生两条审计日志。PostgreSQL 支持 SELECT ... FOR UPDATE，
        第一个事务提交前，第二个事务会等待，从而串行化状态变更。
        SQLite 不支持这个语法，SQLAlchemy 会自动忽略，测试环境仍可运行。
    """
    post = await db.scalar(
        select(MealPost).where(MealPost.id == post_id).with_for_update()
    )
    if post is None:
        raise AppError("POST_NOT_FOUND", "饭帖不存在", status_code=404)
    return post


def _invalid_transition(post: MealPost) -> AppError:
    return AppError(
        "POST_STATUS_TRANSITION_INVALID",
        "当前状态不允许这个操作",
        status_code=409,
        data={"status": post.status},
    )


def _normalize_reason(reason: str) -> str:
    text = reason.strip()
    if len(text) < 2:
        raise AppError("REASON_REQUIRED", "请填写至少 2 个字的原因")
    return text[:200]


def _result(post: MealPost, changed: bool) -> dict[str, Any]:
    return {
        "id": post.id,
        "status": post.status,
        "changed": changed,
        "reviewReason": post.review_reason,
        "reviewedAt": iso(post.reviewed_at),
        "publishedAt": iso(post.published_at),
    }


async def _invalidate_rank_cache() -> None:
    """审核通过或下架后让当日热榜缓存立即失效。

    热榜有短缓存，如果不主动删除，用户最多会看到旧排名若干秒。
    验收标准要求“下架后公开列表立即不可见”，所以这里必须清缓存。
    """
    await delete_key(f"rank:{business_date().isoformat()}")


async def approve_post(
    db: AsyncSession, admin: AdminUser, post_id: str, ip: str | None
) -> dict[str, Any]:
    """通过审核：pending_review -> published。

    已公开的帖子再次点击“通过”直接返回当前状态，不重复写发布时间和审计日志。
    """
    post = await _require_post(db, post_id)
    if post.status == "published":
        return _result(post, changed=False)
    if post.status != "pending_review":
        raise _invalid_transition(post)

    before = _snapshot(post)
    now = now_utc()
    post.status = "published"
    # 发布时间取审核通过的时刻，保证它出现在“今天”的首页和热榜。
    post.published_at = now
    post.reviewed_by = admin.id
    post.reviewed_at = now
    post.review_reason = None
    write_audit(
        db,
        actor=admin,
        action="post.approve",
        target_type="meal_post",
        target_id=post.id,
        before=before,
        after=_snapshot(post),
        ip=ip,
    )
    # 状态变更与审计日志在同一次 commit 中落库，避免只成功一半。
    await db.commit()
    await _invalidate_rank_cache()
    return _result(post, changed=True)


async def reject_post(
    db: AsyncSession, admin: AdminUser, post_id: str, reason: str, ip: str | None
) -> dict[str, Any]:
    """拒绝审核：pending_review -> rejected，必须填写原因。"""
    post = await _require_post(db, post_id)
    text = _normalize_reason(reason)
    if post.status == "rejected":
        return _result(post, changed=False)
    if post.status != "pending_review":
        raise _invalid_transition(post)

    before = _snapshot(post)
    post.status = "rejected"
    post.reviewed_by = admin.id
    post.reviewed_at = now_utc()
    post.review_reason = text
    write_audit(
        db,
        actor=admin,
        action="post.reject",
        target_type="meal_post",
        target_id=post.id,
        reason=text,
        before=before,
        after=_snapshot(post),
        ip=ip,
    )
    await db.commit()
    return _result(post, changed=True)


async def unpublish_post(
    db: AsyncSession, admin: AdminUser, post_id: str, reason: str, ip: str | None
) -> dict[str, Any]:
    """下架已公开内容：published -> unpublished，必须填写原因。"""
    post = await _require_post(db, post_id)
    text = _normalize_reason(reason)
    if post.status == "unpublished":
        return _result(post, changed=False)
    if post.status != "published":
        raise _invalid_transition(post)

    before = _snapshot(post)
    post.status = "unpublished"
    post.reviewed_by = admin.id
    post.reviewed_at = now_utc()
    post.review_reason = text
    write_audit(
        db,
        actor=admin,
        action="post.unpublish",
        target_type="meal_post",
        target_id=post.id,
        reason=text,
        before=before,
        after=_snapshot(post),
        ip=ip,
    )
    await db.commit()
    # 下架后公开列表和热榜都必须立即看不到它。
    await _invalidate_rank_cache()
    return _result(post, changed=True)
