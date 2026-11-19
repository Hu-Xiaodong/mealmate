from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user
from app.core.responses import ok
from app.db.models import User
from app.db.session import get_db
from app.services.rank_service import today_rank

router = APIRouter(tags=["rank"])


@router.get("/rank/today")
async def rank_today(
    viewer: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await today_rank(db, viewer))
