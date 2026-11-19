from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import (
    favorite_flags,
    like_stats,
    main_ingredients_for,
)
from app.core.config import settings
from app.db.models import Like, MealPost, Recipe, User
from app.services.cache import get_json, set_json
from app.services.post_service import load_cards
from app.utils.time import business_date, business_day_bounds, now_utc

MAX_RANK_ITEMS = 20


async def today_rank(db: AsyncSession, viewer: User | None) -> dict[str, Any]:
    stat_date = business_date()
    cache_key = f"rank:{stat_date.isoformat()}"
    cached = await get_json(cache_key)

    if cached is None:
        start, end = business_day_bounds(stat_date)
        rows = (
            await db.execute(
                select(MealPost, func.count(Like.id).label("effective_likes"))
                .join(Like, Like.post_id == MealPost.id)
                .where(
                    MealPost.status == "published",
                    MealPost.published_at >= start,
                    MealPost.published_at < end,
                    Like.active.is_(True),
                    Like.risk_status == "valid",
                )
                .group_by(MealPost.id)
                .having(func.count(Like.id) > 0)
                .order_by(
                    func.count(Like.id).desc(),
                    MealPost.published_at.asc(),
                    MealPost.id.asc(),
                )
                .limit(MAX_RANK_ITEMS)
            )
        ).all()

        posts = [row[0] for row in rows]
        cards = await load_cards(db, posts, None)
        linked_recipes = await _linked_recipes(db, posts)

        items = []
        for index, card in enumerate(cards):
            post = posts[index]
            ingredients, origin = main_ingredients_for(
                post, linked_recipes.get(post.platform_recipe_id or "")
            )
            card.update(
                {
                    "rank": index + 1,
                    "effectiveLikeCount": int(rows[index][1]),
                    "mainIngredients": ingredients,
                    "ingredientOrigin": origin,
                }
            )
            items.append(card)

        cached = {
            "statDate": stat_date.isoformat(),
            "timezone": "Asia/Shanghai",
            "generatedAt": now_utc().isoformat(),
            "items": items,
        }
        await set_json(cache_key, cached, settings.rank_cache_seconds)

    payload = {
        "statDate": cached["statDate"],
        "timezone": cached["timezone"],
        "generatedAt": cached["generatedAt"],
        "items": [dict(item) for item in cached["items"]],
    }

    # 缓存只保存公共事实，本人点赞/收藏状态每次按当前账号覆盖。
    if viewer:
        ids = [item["id"] for item in payload["items"]]
        counts, liked = await like_stats(db, ids, viewer.id)
        saved = await favorite_flags(db, viewer.id, "post", ids)
        for item in payload["items"]:
            item["likedByMe"] = item["id"] in liked
            item["savedByMe"] = item["id"] in saved
            item["likeCount"] = counts.get(item["id"], item["effectiveLikeCount"])
    return payload


async def _linked_recipes(db: AsyncSession, posts: list[MealPost]) -> dict[str, Recipe]:
    ids = {post.platform_recipe_id for post in posts if post.platform_recipe_id}
    if not ids:
        return {}
    rows = (await db.scalars(select(Recipe).where(Recipe.id.in_(ids)))).all()
    return {recipe.id: recipe for recipe in rows}
