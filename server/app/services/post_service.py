from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import (
    authors_map,
    base_post_payload,
    favorite_flags,
    like_stats,
    media_map,
    recipe_payload,
)
from app.db.models import MealPost, Recipe, User


async def load_cards(
    db: AsyncSession,
    posts: Iterable[MealPost],
    viewer_id: str | None,
    distances: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    post_list = list(posts)
    if not post_list:
        return []

    ids = [post.id for post in post_list]
    authors = await authors_map(db, post_list)
    images = await media_map(db, post_list)
    counts, liked = await like_stats(db, ids, viewer_id)
    saved = await favorite_flags(db, viewer_id, "post", ids)

    return [
        base_post_payload(
            post,
            authors.get(post.author_id),
            images.get(post.id, []),
            counts.get(post.id, 0),
            post.id in liked,
            post.id in saved,
            distance_meters=(distances or {}).get(post.id),
        )
        for post in post_list
    ]


async def load_detail(
    db: AsyncSession, post: MealPost, viewer: User | None, distance_meters: int | None = None
) -> dict[str, Any]:
    cards = await load_cards(db, [post], viewer.id if viewer else None, None)
    payload = cards[0]

    linked: Recipe | None = None
    if post.platform_recipe_id:
        linked = await db.get(Recipe, post.platform_recipe_id)
        if linked and linked.status != "published":
            linked = None

    payload["authorRecipe"] = post.author_recipe
    payload["recipe"] = None
    payload["recipeOrigin"] = None
    payload["recipeLabel"] = None

    if post.author_recipe:
        payload["recipeOrigin"] = "author"
        payload["recipeLabel"] = "作者随饭帖提供的做法"
    elif linked:
        recipe_saved = False
        if viewer:
            from app.db.models import Favorite

            recipe_saved = bool(
                await db.scalar(
                    select(Favorite.id).where(
                        Favorite.account_id == viewer.id,
                        Favorite.target_type == "recipe",
                        Favorite.target_id == linked.id,
                    )
                )
            )
        payload["recipe"] = recipe_payload(linked, saved=recipe_saved)
        payload["recipeOrigin"] = "platform_reference"
        payload["recipeLabel"] = "来自平台菜谱 · 参考做法"

    payload["takeawayStore"] = post.takeaway_store if post.source == "takeaway" else None
    payload["dineInAddress"] = post.dine_in_address if post.source == "dine_in" else None
    payload["coarseArea"] = post.coarse_area
    if distance_meters is not None:
        payload["distanceMeters"] = distance_meters
    return payload
