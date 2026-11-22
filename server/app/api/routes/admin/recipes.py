from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import AdminPrincipal, client_ip, require_permission
from app.core.responses import ok
from app.db.session import get_db
from app.schemas import RecipeInput
from app.services.admin_recipe_service import (
    archive_recipe,
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
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    principal: AdminPrincipal = Depends(require_permission("recipe.manage")),
    db: AsyncSession = Depends(get_db),
):
    """菜谱列表，支持标题关键词、状态筛选与游标分页。"""
    return ok(
        await list_admin_recipes(
            db, keyword=keyword, status=status_filter, cursor=cursor, limit=limit
        )
    )


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
