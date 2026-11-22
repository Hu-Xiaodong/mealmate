"""管理后台的菜谱维护。

菜谱是平台内容，和用户饭帖不同：它由运营创建、编辑、上下架，
因此单独放在后台服务里，普通用户端只读取已发布数据。
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import iso, media_url
from app.core.errors import AppError
from app.core.security import new_id
from app.db.models import AdminUser, Recipe, RecipeCategory
from app.schemas import RecipeInput
from app.services.audit_service import write_audit
from app.utils.cursor import decode_cursor, encode_cursor
from app.utils.time import now_utc

MAX_PAGE_SIZE = 50
VALID_STATUSES = {"draft", "published", "archived"}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _snapshot(recipe: Recipe) -> dict[str, Any]:
    """菜谱关键字段快照，用于审计日志对比。"""
    return {
        "title": recipe.title,
        "coverUrl": recipe.cover_url,
        "totalMinutes": recipe.total_minutes,
        "categories": recipe.category_codes,
        "servings": recipe.servings,
        "status": recipe.status,
        "validationStatus": recipe.validation_status,
    }


def _payload(recipe: Recipe) -> dict[str, Any]:
    """后台编辑需要的完整字段。

    同时返回 coverKey（数据库原始对象键）和 coverImage（可直接预览的地址）：
    编辑表单提交时用 coverKey，页面展示时用 coverImage。
    """
    return {
        "id": recipe.id,
        "title": recipe.title,
        "coverImage": media_url(recipe.cover_url),
        "coverKey": recipe.cover_url,
        "totalMinutes": recipe.total_minutes,
        "tools": recipe.tool_codes,
        "categories": recipe.category_codes,
        "servings": recipe.servings,
        "mainIngredients": recipe.main_ingredients,
        "ingredients": recipe.ingredients,
        "steps": recipe.steps,
        "preconditions": recipe.preconditions,
        "contentOrigin": recipe.content_origin,
        "validationStatus": recipe.validation_status,
        "status": recipe.status,
        "createdAt": iso(recipe.created_at),
    }


async def _sync_categories(db: AsyncSession, recipe_id: str, codes: list[str]) -> None:
    """把分类关联表刷新成最新集合。

    为什么同时保留 recipes.category_codes 和 recipe_categories：
    列表筛选走关联表（可加索引），详情展示走 JSON 字段（读取简单）。
    两边必须同步，否则会出现“详情显示有分类、筛选却查不到”的脏数据。
    """
    await db.execute(delete(RecipeCategory).where(RecipeCategory.recipe_id == recipe_id))
    for code in codes:
        db.add(RecipeCategory(id=new_id("rc"), recipe_id=recipe_id, code=code))


async def list_admin_recipes(
    db: AsyncSession,
    *,
    keyword: str | None,
    status: str | None,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    limit = min(max(limit, 1), MAX_PAGE_SIZE)
    if status and status not in VALID_STATUSES:
        raise AppError("RECIPE_STATUS_INVALID", "菜谱状态筛选值不正确")

    conditions = []
    if status:
        conditions.append(Recipe.status == status)
    if keyword and keyword.strip():
        conditions.append(Recipe.title.contains(keyword.strip()))

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

    rows = (
        await db.scalars(
            select(Recipe)
            .where(*conditions)
            .order_by(Recipe.created_at.desc(), Recipe.id.desc())
            .limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor({"createdAt": last.created_at.isoformat(), "id": last.id})
    return {
        "items": [_payload(recipe) for recipe in page],
        "nextCursor": next_cursor,
        "hasMore": has_more,
    }


async def get_admin_recipe(db: AsyncSession, recipe_id: str) -> dict[str, Any]:
    recipe = await db.get(Recipe, recipe_id)
    if recipe is None:
        raise AppError("RECIPE_NOT_FOUND", "菜谱不存在", status_code=404)
    return _payload(recipe)


def _apply(recipe: Recipe, body: RecipeInput) -> None:
    recipe.title = body.title
    recipe.cover_url = body.cover_url
    recipe.total_minutes = body.total_minutes
    recipe.tool_codes = body.tool_codes
    recipe.category_codes = body.category_codes
    recipe.servings = body.servings
    recipe.main_ingredients = body.main_ingredients
    recipe.ingredients = [item.model_dump() for item in body.ingredients]
    recipe.steps = body.steps
    recipe.preconditions = body.preconditions
    recipe.content_origin = body.content_origin
    recipe.validation_status = body.validation_status
    recipe.status = body.status


async def create_recipe(
    db: AsyncSession, admin: AdminUser, body: RecipeInput, ip: str | None
) -> dict[str, Any]:
    recipe = Recipe(id=new_id("r"), created_at=now_utc())
    _apply(recipe, body)
    db.add(recipe)
    await db.flush()
    await _sync_categories(db, recipe.id, body.category_codes)
    write_audit(
        db,
        actor=admin,
        action="recipe.create",
        target_type="recipe",
        target_id=recipe.id,
        after=_snapshot(recipe),
        ip=ip,
    )
    await db.commit()
    return _payload(recipe)


async def update_recipe(
    db: AsyncSession, admin: AdminUser, recipe_id: str, body: RecipeInput, ip: str | None
) -> dict[str, Any]:
    recipe = await db.get(Recipe, recipe_id)
    if recipe is None:
        raise AppError("RECIPE_NOT_FOUND", "菜谱不存在", status_code=404)
    before = _snapshot(recipe)
    _apply(recipe, body)
    await _sync_categories(db, recipe.id, body.category_codes)
    write_audit(
        db,
        actor=admin,
        action="recipe.update",
        target_type="recipe",
        target_id=recipe.id,
        before=before,
        after=_snapshot(recipe),
        ip=ip,
    )
    await db.commit()
    return _payload(recipe)


async def archive_recipe(
    db: AsyncSession, admin: AdminUser, recipe_id: str, ip: str | None
) -> dict[str, Any]:
    """下架菜谱。

    不做物理删除：饭帖可能引用平台菜谱，物理删除会让历史内容失去上下文。
    改为 status=archived，用户端列表和详情立即不可见，但数据仍可恢复。
    """
    recipe = await db.get(Recipe, recipe_id)
    if recipe is None:
        raise AppError("RECIPE_NOT_FOUND", "菜谱不存在", status_code=404)
    if recipe.status == "archived":
        return {"id": recipe.id, "status": recipe.status, "changed": False}
    before = _snapshot(recipe)
    recipe.status = "archived"
    write_audit(
        db,
        actor=admin,
        action="recipe.archive",
        target_type="recipe",
        target_id=recipe.id,
        before=before,
        after=_snapshot(recipe),
        ip=ip,
    )
    await db.commit()
    return {"id": recipe.id, "status": recipe.status, "changed": True}
