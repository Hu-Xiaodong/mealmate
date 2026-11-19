from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import iso, media_map
from app.core.errors import AppError
from app.db.models import Favorite, MealPost, Recipe, User
from app.services.post_service import load_cards
from app.services.storage import object_url
from app.utils.cursor import decode_cursor, encode_cursor

PAGE_SIZE = 20
MAX_PAGE_SIZE = 50


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def my_posts(
    db: AsyncSession, viewer: User, cursor: str | None, limit: int
) -> dict[str, Any]:
    limit = min(max(limit, 1), MAX_PAGE_SIZE)
    conditions = [MealPost.author_id == viewer.id]
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
    items = await load_cards(db, page, viewer.id)
    # 作者需要看到审核结果与原因，否则被拒绝后不知道要改什么。
    # 这两个字段只出现在“我的发布”，不进入公开列表。
    for item, post in zip(items, page, strict=False):
        item["reviewReason"] = post.review_reason
        item["reviewedAt"] = iso(post.reviewed_at)
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor({"createdAt": last.created_at.isoformat(), "id": last.id})
    return {"items": items, "nextCursor": next_cursor, "hasMore": has_more}


async def my_favorites(
    db: AsyncSession, viewer: User, cursor: str | None, limit: int
) -> dict[str, Any]:
    limit = min(max(limit, 1), MAX_PAGE_SIZE)
    conditions = [Favorite.account_id == viewer.id]
    cursor_data = decode_cursor(cursor)
    if cursor:
        saved_at = _parse_dt(cursor_data.get("savedAt") if cursor_data else None)
        cursor_id = cursor_data.get("id") if cursor_data else None
        if saved_at is None or not cursor_id:
            raise AppError("CURSOR_INVALID", "分页游标无效，请刷新后重试")
        conditions.append(
            or_(
                Favorite.saved_at < saved_at,
                and_(Favorite.saved_at == saved_at, Favorite.id < cursor_id),
            )
        )

    rows = (
        await db.scalars(
            select(Favorite)
            .where(*conditions)
            .order_by(Favorite.saved_at.desc(), Favorite.id.desc())
            .limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    page = rows[:limit]

    post_ids = [row.target_id for row in page if row.target_type == "post"]
    recipe_ids = [row.target_id for row in page if row.target_type == "recipe"]

    posts = (
        (await db.scalars(select(MealPost).where(MealPost.id.in_(post_ids)))).all()
        if post_ids
        else []
    )
    recipes = (
        (await db.scalars(select(Recipe).where(Recipe.id.in_(recipe_ids)))).all()
        if recipe_ids
        else []
    )
    post_map = {post.id: post for post in posts}
    recipe_map = {recipe.id: recipe for recipe in recipes}
    images = await media_map(db, posts)

    items = []
    for favorite in page:
        if favorite.target_type == "post":
            post = post_map.get(favorite.target_id)
            available = post is not None and post.status == "published"
            items.append(
                {
                    "targetType": "post",
                    "targetId": favorite.target_id,
                    "title": post.title if available else "收藏内容暂不可用",
                    "summary": post.review if available else "该饭帖已下架或被作者删除",
                    "coverImage": images.get(favorite.target_id, [None])[0] if available else None,
                    "savedAt": iso(favorite.saved_at),
                    "available": available,
                }
            )
        else:
            recipe = recipe_map.get(favorite.target_id)
            available = recipe is not None and recipe.status == "published"
            items.append(
                {
                    "targetType": "recipe",
                    "targetId": favorite.target_id,
                    "title": recipe.title if available else "收藏内容暂不可用",
                    "summary": (
                        f"{recipe.total_minutes} 分钟 · {recipe.preconditions or '快手家常'}"
                        if available
                        else "该菜谱已下架"
                    ),
                    "coverImage": object_url(recipe.cover_url) if available else None,
                    "savedAt": iso(favorite.saved_at),
                    "available": available,
                }
            )

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor({"savedAt": last.saved_at.isoformat(), "id": last.id})
    return {"items": items, "nextCursor": next_cursor, "hasMore": has_more}
