from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.responses import ok
from app.db.models import User
from app.db.session import get_db
from app.services.me_service import draft_detail, my_drafts, my_favorites, my_posts

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/posts")
async def mine_posts(
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await my_posts(db, user, cursor, limit))


@router.get("/drafts")
async def mine_drafts(
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await my_drafts(db, user, cursor, limit))


@router.get("/drafts/{post_id}")
async def mine_draft_detail(
    post_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await draft_detail(db, user, post_id))


@router.get("/favorites")
async def mine_favorites(
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await my_favorites(db, user, cursor, limit))
