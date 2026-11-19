from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user
from app.core.responses import ok
from app.db.models import User
from app.db.session import get_db
from app.services.recipe_service import get_recipe, list_recipes

router = APIRouter(prefix="/recipes", tags=["recipes"])


@router.get("")
async def recipes(
    category: Literal["recommended", "quick", "one_pot", "few"] = "recommended",
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    viewer: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await list_recipes(db, viewer, category, cursor, limit))


@router.get("/{recipe_id}")
async def recipe_detail(
    recipe_id: str,
    viewer: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await get_recipe(db, viewer, recipe_id))
