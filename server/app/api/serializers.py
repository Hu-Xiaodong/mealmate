"""统一的响应拼装，保证首页、热榜、详情、我的使用同一事实来源。"""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Favorite, Like, MealPost, MediaAsset, Recipe, User
from app.services.storage import object_url


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def media_url(storage_key: str) -> str:
    return object_url(storage_key) or ""


async def authors_map(db: AsyncSession, posts: Iterable[MealPost]) -> dict[str, User]:
    ids = {post.author_id for post in posts}
    if not ids:
        return {}
    rows = (await db.scalars(select(User).where(User.id.in_(ids)))).all()
    return {user.id: user for user in rows}


async def media_map(db: AsyncSession, posts: Iterable[MealPost]) -> dict[str, list[str]]:
    """按饭帖聚合图片 URL，缺失资产跳过但不改变有效图片顺序。"""
    all_asset_ids = {asset_id for post in posts for asset_id in post.image_asset_ids}
    assets: dict[str, MediaAsset] = {}
    if all_asset_ids:
        rows = (
            await db.scalars(
                select(MediaAsset).where(
                    MediaAsset.id.in_(all_asset_ids), MediaAsset.status == "ready"
                )
            )
        ).all()
        assets = {asset.id: asset for asset in rows}

    result: dict[str, list[str]] = {}
    for post in posts:
        urls = [
            media_url(assets[asset_id].storage_key)
            for asset_id in post.image_asset_ids
            if asset_id in assets
        ]
        result[post.id] = urls
    return result


async def like_stats(
    db: AsyncSession, post_ids: Iterable[str], viewer_id: str | None
) -> tuple[dict[str, int], set[str]]:
    ids = list(post_ids)
    if not ids:
        return {}, set()

    count_rows = (
        await db.execute(
            select(Like.post_id, func.count(Like.id))
            .where(
                Like.post_id.in_(ids),
                Like.active.is_(True),
                Like.risk_status == "valid",
            )
            .group_by(Like.post_id)
        )
    ).all()
    counts = {post_id: int(count) for post_id, count in count_rows}

    liked: set[str] = set()
    if viewer_id:
        liked = set(
            (
                await db.scalars(
                    select(Like.post_id).where(
                        Like.account_id == viewer_id,
                        Like.post_id.in_(ids),
                        Like.active.is_(True),
                        Like.risk_status == "valid",
                    )
                )
            ).all()
        )
    return counts, liked


async def favorite_flags(
    db: AsyncSession,
    viewer_id: str | None,
    target_type: str,
    target_ids: Iterable[str],
) -> set[str]:
    ids = list(target_ids)
    if not viewer_id or not ids:
        return set()
    return set(
        (
            await db.scalars(
                select(Favorite.target_id).where(
                    Favorite.account_id == viewer_id,
                    Favorite.target_type == target_type,
                    Favorite.target_id.in_(ids),
                )
            )
        ).all()
    )


def author_payload(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "nickname": user.nickname,
        "avatarUrl": user.avatar_url,
    }


def base_post_payload(
    post: MealPost,
    author: User | None,
    images: list[str],
    like_count: int,
    liked: bool,
    saved: bool,
    *,
    distance_meters: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": post.id,
        "title": post.title,
        "review": post.review,
        "source": post.source,
        "coverImage": images[0] if images else None,
        "images": images,
        "imageCount": len(images),
        "author": author_payload(author),
        "publishedAt": iso(post.published_at),
        "likeCount": like_count,
        "likedByMe": liked,
        "savedByMe": saved,
        "status": post.status,
        # 人均价格为空时前端不展示，不做 0 元兜底，避免误导。
        "avgPrice": post.avg_price,
        # 老数据没有这个字段时数据库返回 None，这里统一成空列表。
        "tasteTags": post.taste_tags or [],
    }
    if distance_meters is not None:
        payload["distanceMeters"] = distance_meters
    return payload


def recipe_payload(recipe: Recipe, *, saved: bool = False) -> dict[str, Any]:
    return {
        "id": recipe.id,
        "title": recipe.title,
        "coverImage": media_url(recipe.cover_url),
        "totalMinutes": recipe.total_minutes,
        "tools": recipe.tool_codes,
        "categories": recipe.category_codes,
        "servings": recipe.servings,
        "mainIngredients": recipe.main_ingredients[:3],
        "ingredients": recipe.ingredients,
        "steps": recipe.steps,
        "preconditions": recipe.preconditions,
        "contentOrigin": recipe.content_origin,
        "validationStatus": recipe.validation_status,
        "savedByMe": saved,
    }


def _ingredient_name(raw: str) -> str:
    text = raw.strip()
    for sep in (" ", "，", ",", "：", ":", "（", "("):
        text = text.split(sep, 1)[0]
    return text[:12]


def main_ingredients_for(post: MealPost, linked: Recipe | None) -> tuple[list[str], str | None]:
    """标签只来自明确的作者食材或平台关联菜谱，不从图片或菜名猜测。"""
    if post.author_recipe and post.author_recipe.get("ingredients"):
        names = [
            _ingredient_name(item)
            for item in post.author_recipe["ingredients"][:3]
            if _ingredient_name(item)
        ]
        if names:
            return names, "author"
    if linked and linked.main_ingredients:
        return linked.main_ingredients[:3], "platform_reference"
    return [], None
