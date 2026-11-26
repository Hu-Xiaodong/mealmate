from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import AdminPrincipal, client_ip, require_permission
from app.core.responses import ok
from app.db.session import get_db
from app.schemas import RecipeBatchRequest, RecipeInput
from app.services.admin_recipe_service import (
    archive_recipe,
    batch_archive_recipes,
    batch_delete_recipes,
    batch_publish_recipes,
    create_recipe,
    get_admin_recipe,
    list_admin_recipes,
    update_recipe,
)

router = APIRouter(prefix="/admin/recipes", tags=["admin-recipes"])


@router.get("")
async def list_recipes(
    keyword: str | None = Query(default=None, max_length=40),
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50, alias="pageSize"),
    principal: AdminPrincipal = Depends(require_permission("recipe.manage")),
    db: AsyncSession = Depends(get_db),
):
    """菜谱列表，支持标题关键词、状态筛选与页码分页。"""
    return ok(
        await list_admin_recipes(
            db, keyword=keyword, status=status_filter, page=page, page_size=page_size
        )
    )


@router.post("/batch-publish")
async def batch_publish(
    body: RecipeBatchRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("recipe.manage")),
    db: AsyncSession = Depends(get_db),
):
    """批量上架菜谱。逐条执行并返回每条结果，已上架的记为跳过。"""
    data = await batch_publish_recipes(
        db, principal.admin, body.recipe_ids, client_ip(request)
    )
    return ok(data, f"批量上架完成：成功 {data['succeeded']} 条")


@router.post("/batch-archive")
async def batch_archive(
    body: RecipeBatchRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("recipe.manage")),
    db: AsyncSession = Depends(get_db),
):
    """批量下架菜谱（软下架）。历史饭帖的关联仍然保留。"""
    data = await batch_archive_recipes(
        db, principal.admin, body.recipe_ids, client_ip(request)
    )
    return ok(data, f"批量下架完成：成功 {data['succeeded']} 条")


@router.post("/batch-delete")
async def batch_delete(
    body: RecipeBatchRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("recipe.manage")),
    db: AsyncSession = Depends(get_db),
):
    """批量删除菜谱。

    物理删除，只清理没有任何饭帖引用的菜谱；
    被饭帖引用的菜谱会跳过并说明原因，避免历史内容失去来源。
    """
    data = await batch_delete_recipes(
        db, principal.admin, body.recipe_ids, client_ip(request)
    )
    return ok(data, f"批量删除完成：成功 {data['succeeded']} 条")


@router.get("/{recipe_id}")
async def recipe_detail(
    recipe_id: str,
    principal: AdminPrincipal = Depends(require_permission("recipe.manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(await get_admin_recipe(db, recipe_id))


@router.post("")
async def create(
    body: RecipeInput,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("recipe.manage")),
    db: AsyncSession = Depends(get_db),
):
    """新增菜谱。创建后可以直接以 published 状态公开，也可以先存草稿。"""
    return ok(
        await create_recipe(db, principal.admin, body, client_ip(request)),
        "菜谱已创建",
    )


@router.put("/{recipe_id}")
async def update(
    recipe_id: str,
    body: RecipeInput,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("recipe.manage")),
    db: AsyncSession = Depends(get_db),
):
    return ok(
        await update_recipe(db, principal.admin, recipe_id, body, client_ip(request)),
        "菜谱已保存",
    )


@router.post("/{recipe_id}/archive")
async def archive(
    recipe_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("recipe.manage")),
    db: AsyncSession = Depends(get_db),
):
    """下架菜谱（软下架）。历史饭帖的关联仍然保留。"""
    data = await archive_recipe(db, principal.admin, recipe_id, client_ip(request))
    return ok(data, "菜谱已下架" if data["changed"] else "该菜谱已是下架状态")
