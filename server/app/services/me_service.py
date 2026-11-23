from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import iso, media_map
from app.core.errors import AppError
from app.db.models import Favorite, MealPost, Recipe, User
from app.services.post_service import load_cards
from app.services.post_write_service import draft_payload
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
    # “我的发布”只展示作者自己需要管理的正式内容：
    # 草稿有单独的草稿箱，已删除的内容不应再出现在列表里。
    conditions = [
        MealPost.author_id == viewer.id,
        MealPost.status.notin_(["draft", "deleted"]),
    ]
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


async def my_drafts(
    db: AsyncSession, viewer: User, cursor: str | None, limit: int
) -> dict[str, Any]:
    """草稿箱列表。

    排序使用 updated_at 而不是 created_at：
    用户更关心“最近改过哪一条”，而不是“最早什么时候建的草稿”。
    分页游标也对应地携带 updatedAt，避免翻页时顺序错乱。
    """
    limit = min(max(limit, 1), MAX_PAGE_SIZE)
    conditions = [MealPost.author_id == viewer.id, MealPost.status == "draft"]
    cursor_data = decode_cursor(cursor)
    if cursor:
        updated = _parse_dt(cursor_data.get("updatedAt") if cursor_data else None)
        cursor_id = cursor_data.get("id") if cursor_data else None
        if updated is None or not cursor_id:
            raise AppError("CURSOR_INVALID", "分页游标无效，请刷新后重试")
        conditions.append(
            or_(
                MealPost.updated_at < updated,
                and_(MealPost.updated_at == updated, MealPost.id < cursor_id),
            )
        )

    rows = (
        await db.scalars(
            select(MealPost)
            .where(*conditions)
            .order_by(MealPost.updated_at.desc(), MealPost.id.desc())
            .limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    items = await load_cards(db, page, viewer.id)
    for item, post in zip(items, page, strict=False):
        item["updatedAt"] = iso(post.updated_at)
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor(
            {"updatedAt": last.updated_at.isoformat(), "id": last.id}
        )
    return {"items": items, "nextCursor": next_cursor, "hasMore": has_more}


async def draft_detail(db: AsyncSession, viewer: User, post_id: str) -> dict[str, Any]:
    """读取自己的草稿原始字段，供编辑页回填。"""
    post = await db.get(MealPost, post_id)
    # 同样用 404 而不是 403，避免别人枚举草稿编号。
    if post is None or post.author_id != viewer.id or post.status != "draft":
        raise AppError("POST_NOT_FOUND", "草稿不存在或已发布", status_code=404)
    return await draft_payload(db, post)


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
                        (
                            f"{recipe.total_minutes} 分钟 · "
                            f"{recipe.preconditions or '快手家常'}"
                        )
                        if available and recipe.total_minutes is not None
                        else (
                            f"耗时未标注 · {recipe.preconditions or '家常菜'}"
                            if available
                            else "该菜谱已下架"
                        )
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
