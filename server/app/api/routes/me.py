from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.responses import ok
from app.db.models import User
from app.db.session import get_db
from app.services.me_service import my_favorites, my_posts

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/posts")
async def mine_posts(
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await my_posts(db, user, cursor, limit))


@router.get("/favorites")
async def mine_favorites(
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await my_favorites(db, user, cursor, limit))
