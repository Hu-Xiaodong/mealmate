from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import favorite_flags, recipe_payload
from app.core.errors import AppError
from app.db.models import Recipe, RecipeCategory, User
from app.utils.cursor import decode_cursor, encode_cursor

PAGE_SIZE = 20
VALID_CATEGORIES = {"recommended", "quick", "one_pot", "few"}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def list_recipes(
    db: AsyncSession, viewer: User | None, category: str, cursor: str | None, limit: int
) -> dict[str, Any]:
    limit = min(max(limit, 1), 50)
    if category not in VALID_CATEGORIES:
        raise AppError("CATEGORY_INVALID", "未知的菜谱分类")

    conditions = [Recipe.status == "published"]
    cursor_data = decode_cursor(cursor)
    if cursor:
        created = _parse_dt(cursor_data.get("createdAt") if cursor_data else None)
        cursor_id = cursor_data.get("id") if cursor_data else None
        if created is None or not cursor_id:
            raise AppError("CURSOR_INVALID", "分页游标无效，请刷新后重试")
        conditions.append(
            or_(
                Recipe.created_at < created,
                and_(Recipe.created_at == created, Recipe.id < cursor_id),
            )
        )

    recipe_ids = (
        select(RecipeCategory.recipe_id).where(RecipeCategory.code == category)
    )
    rows = (
        await db.scalars(
            select(Recipe)
            .where(*conditions, Recipe.id.in_(recipe_ids))
            .order_by(Recipe.created_at.desc(), Recipe.id.desc())
            .limit(limit + 1)
        )
    ).all()

    has_more = len(rows) > limit
    page = rows[:limit]
    saved = await favorite_flags(
        db, viewer.id if viewer else None, "recipe", [recipe.id for recipe in page]
    )
    items = [recipe_payload(recipe, saved=recipe.id in saved) for recipe in page]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor({"createdAt": last.created_at.isoformat(), "id": last.id})

    return {"items": items, "nextCursor": next_cursor, "hasMore": has_more}


async def get_recipe(db: AsyncSession, viewer: User | None, recipe_id: str) -> dict[str, Any]:
    recipe = await db.get(Recipe, recipe_id)
    if recipe is None or recipe.status != "published":
        raise AppError("RECIPE_NOT_FOUND", "这道菜谱暂时无法查看", status_code=404)
    saved = await favorite_flags(
        db, viewer.id if viewer else None, "recipe", [recipe.id]
    )
    return recipe_payload(recipe, saved=recipe.id in saved)
