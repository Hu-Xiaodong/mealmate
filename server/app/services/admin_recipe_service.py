"""管理后台的菜谱维护。

菜谱是平台内容，和用户饭帖不同：它由运营创建、编辑、上下架，
因此单独放在后台服务里，普通用户端只读取已发布数据。
"""

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import iso, media_url
from app.core.errors import AppError
from app.core.security import new_id
from app.db.models import AdminUser, Favorite, MealPost, Recipe, RecipeCategory
from app.schemas import RecipeInput
from app.services.audit_service import write_audit
from app.utils.time import now_utc

MAX_PAGE_SIZE = 50
VALID_STATUSES = {"draft", "published", "archived"}


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


async def sync_categories(db: AsyncSession, recipe_id: str, codes: list[str]) -> None:
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
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """后台菜谱列表，支持标题关键词、状态筛选和页码分页。

    为什么用页码分页：运营需要看到“共多少道、当前第几页”并直接跳页，
    而菜谱总量会随知识库导入持续增长，不能一次性全部返回。
    """
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    page = max(page, 1)
    if status and status not in VALID_STATUSES:
        raise AppError("RECIPE_STATUS_INVALID", "菜谱状态筛选值不正确")

    conditions = []
    if status:
        conditions.append(Recipe.status == status)
    if keyword and keyword.strip():
        conditions.append(Recipe.title.contains(keyword.strip()))

    total = int(
        await db.scalar(select(func.count()).select_from(Recipe).where(*conditions)) or 0
    )
    rows = (
        await db.scalars(
            select(Recipe)
            .where(*conditions)
            .order_by(Recipe.created_at.desc(), Recipe.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "items": [_payload(recipe) for recipe in rows],
        "total": total,
        "page": page,
        "pageSize": page_size,
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
    # 客户端菜谱列表是按分类筛选的（推荐/快手/一锅/少食材），
    # 分类关联表里没有记录的菜谱，用户在任何一个分类下都看不到。
    # 因此已发布的菜谱如果运营没选分类，默认归入“推荐”，
    # 保证“上架即可见”，而不是悄悄消失在列表外。
    if recipe.status == "published" and not recipe.category_codes:
        recipe.category_codes = ["recommended"]


async def create_recipe(
    db: AsyncSession, admin: AdminUser, body: RecipeInput, ip: str | None
) -> dict[str, Any]:
    recipe = Recipe(id=new_id("r"), created_at=now_utc())
    _apply(recipe, body)
    db.add(recipe)
    await db.flush()
    await sync_categories(db, recipe.id, recipe.category_codes)
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
    await sync_categories(db, recipe.id, recipe.category_codes)
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


async def _batch_set_status(
    db: AsyncSession,
    admin: AdminUser,
    recipe_ids: list[str],
    ip: str | None,
    *,
    target_status: str,
    action: str,
    action_label: str,
) -> dict[str, Any]:
    """批量把菜谱改成同一个状态（上架或下架），逐条返回结果。

    作用：
        上架和下架只有“目标状态、审计动作名、提示文案”三点不同，
        其余逻辑完全一致，因此抽成一个内部函数，避免两份几乎相同的代码
        在以后修改时只改了一处。
    哪里用到：
        batch_publish_recipes（上架）与 batch_archive_recipes（下架）。
    为什么逐条提交而不是整批一个事务：
        批量操作允许部分成功。比如勾选 10 道菜谱，其中 1 道已被其他管理员删掉，
        其余 9 道仍应正常上下架；整批事务会因为那 1 道报错而全部回滚，
        运营只能重新猜测哪一条有问题。逐条提交能让每条结果独立、可解释。
    为什么状态相同要记为“跳过”而不是“失败”：
        重复点按钮、或两个人同时操作时，“已经是目标状态”不是错误，
        只是这次不需要改动；分开统计能让运营一眼看出真正失败的是哪几条。
    """
    results: list[dict[str, Any]] = []
    succeeded = 0
    skipped = 0
    for recipe_id in recipe_ids:
        recipe = await db.get(Recipe, recipe_id)
        if recipe is None:
            # 单条不存在不影响整批：记录下来，前端会在结果弹窗里单独展示。
            results.append(
                {
                    "recipeId": recipe_id,
                    "title": "",
                    "ok": False,
                    "errorCode": "RECIPE_NOT_FOUND",
                    "message": "菜谱不存在，可能已被其他管理员删除",
                }
            )
            continue
        if recipe.status == target_status:
            skipped += 1
            results.append(
                {
                    "recipeId": recipe.id,
                    "title": recipe.title,
                    "ok": True,
                    "skipped": True,
                    "message": f"该菜谱已是{action_label}状态",
                }
            )
            continue
        before = _snapshot(recipe)
        recipe.status = target_status
        if target_status == "published" and not recipe.category_codes:
            # 知识库生成的草稿默认没有分类：直接改 published 虽然能通过详情接口访问，
            # 但移动端列表按分类筛选时会查不到，表现为“后台已上架、App 没同步”。
            # 上架时在这里兜底补一个“推荐”，并同步关联表，保证列表立即可见。
            recipe.category_codes = ["recommended"]
            await sync_categories(db, recipe.id, recipe.category_codes)
        write_audit(
            db,
            actor=admin,
            action=action,
            target_type="recipe",
            target_id=recipe.id,
            before=before,
            after=_snapshot(recipe),
            ip=ip,
        )
        await db.commit()
        succeeded += 1
        results.append(
            {
                "recipeId": recipe.id,
                "title": recipe.title,
                "ok": True,
                "message": f"已{action_label}",
            }
        )
    return {
        "succeeded": succeeded,
        "failed": len(results) - succeeded - skipped,
        "skipped": skipped,
        "results": results,
    }


async def batch_publish_recipes(
    db: AsyncSession, admin: AdminUser, recipe_ids: list[str], ip: str | None
) -> dict[str, Any]:
    """批量上架菜谱。

    草稿和下架的菜谱都会变成 published，用户端立即可以搜索和查看。
    为什么不在上架前强制“试做通过”：
        平台允许运营先上架、再补试做记录；强制校验会把上下架绑死在
        内容质量流程上，遇到紧急调整时反而挡住运营。
    哪里用到：
        管理后台菜谱列表的“批量上架”按钮。
    """
    return await _batch_set_status(
        db,
        admin,
        recipe_ids,
        ip,
        target_status="published",
        action="recipe.publish",
        action_label="上架",
    )


async def batch_archive_recipes(
    db: AsyncSession, admin: AdminUser, recipe_ids: list[str], ip: str | None
) -> dict[str, Any]:
    """批量下架菜谱（软下架）。

    和单个下架一样只把 status 改成 archived，不删除数据：
    饭帖可能引用平台菜谱，物理删除会让历史内容失去上下文；
    下架后用户端立即不可见，运营之后仍可以重新上架。
    哪里用到：
        管理后台菜谱列表的“批量下架”按钮。
    """
    return await _batch_set_status(
        db,
        admin,
        recipe_ids,
        ip,
        target_status="archived",
        action="recipe.archive",
        action_label="下架",
    )


async def batch_delete_recipes(
    db: AsyncSession, admin: AdminUser, recipe_ids: list[str], ip: str | None
) -> dict[str, Any]:
    """批量物理删除菜谱，逐条返回结果。

    为什么“下架”之外还需要“删除”：
        下架适合临时隐藏；导入错误、重复导入、测试数据这类菜谱
        没有任何保留价值，长期堆在库里会污染搜索与统计，需要真正清理。
    为什么有饭帖引用时拒绝删除，而不是把引用置空：
        饭帖里的 platformRecipeId 是“这道菜来自哪个平台菜谱”的唯一线索，
        置空后历史饭帖会变成一条无法追溯的孤立内容。此时更合适的处理是
        提示运营改为下架；等引用饭帖都删除后，再回来删除菜谱。
    为什么顺带删除收藏记录：
        收藏表的 targetId 没有外键约束（它同时存放帖子、菜谱等多种目标），
        菜谱删掉后收藏记录会变成指向不存在对象的“孤儿数据”，
        用户端收藏列表就会出现打不开的条目，因此必须一起清理。
    为什么逐条提交：
        与批量上下架相同，允许部分成功；某一条被引用只跳过这一条，
        其余可删除的菜谱仍然会被清理。
    哪里用到：
        管理后台菜谱列表的“批量删除”按钮。
    """
    results: list[dict[str, Any]] = []
    succeeded = 0
    skipped = 0
    for recipe_id in recipe_ids:
        recipe = await db.get(Recipe, recipe_id)
        if recipe is None:
            results.append(
                {
                    "recipeId": recipe_id,
                    "title": "",
                    "ok": False,
                    "errorCode": "RECIPE_NOT_FOUND",
                    "message": "菜谱不存在，可能已被其他管理员删除",
                }
            )
            continue
        # 统计有多少条饭帖把这道菜谱作为来源。只查数量，不加载帖子正文，
        # 因为这里只需要判断“能不能删”，不需要展示帖子内容。
        reference_count = await db.scalar(
            select(func.count())
            .select_from(MealPost)
            .where(MealPost.platform_recipe_id == recipe_id)
        )
        if reference_count:
            skipped += 1
            results.append(
                {
                    "recipeId": recipe.id,
                    "title": recipe.title,
                    "ok": True,
                    "skipped": True,
                    "message": f"有 {reference_count} 条饭帖引用了该菜谱，不能删除；可改为下架",
                }
            )
            continue
        before = _snapshot(recipe)
        # 先清理子表与收藏，再删主表，避免留下外键悬空或收藏孤儿数据。
        await db.execute(
            delete(RecipeCategory).where(RecipeCategory.recipe_id == recipe_id)
        )
        await db.execute(
            delete(Favorite).where(
                Favorite.target_type == "recipe", Favorite.target_id == recipe_id
            )
        )
        write_audit(
            db,
            actor=admin,
            action="recipe.delete",
            target_type="recipe",
            target_id=recipe.id,
            before=before,
            # 物理删除后没有“变更后快照”，after 留空表示对象已不存在。
            after=None,
            ip=ip,
        )
        await db.delete(recipe)
        await db.commit()
        succeeded += 1
        results.append(
            {
                "recipeId": recipe.id,
                "title": recipe.title,
                "ok": True,
                "message": "已删除",
            }
        )
    return {
        "succeeded": succeeded,
        "failed": len(results) - succeeded - skipped,
        "skipped": skipped,
        "results": results,
    }
