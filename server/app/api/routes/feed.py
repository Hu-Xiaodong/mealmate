from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user
from app.core.responses import ok
from app.db.models import User
from app.db.session import get_db
from app.services.feed_service import list_feed

router = APIRouter(tags=["feed"])


@router.get("/feed")
async def feed(
    filter: Literal["all", "near"] = "all",
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    lat: float | None = None,
    lng: float | None = None,
    radius: int = Query(default=3000, ge=500, le=10000),
    viewer: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    data = await list_feed(
        db,
        viewer,
        filter_type=filter,
        cursor=cursor,
        limit=limit,
        lat=lat,
        lng=lng,
        radius_m=radius,
    )
    return ok(data)
