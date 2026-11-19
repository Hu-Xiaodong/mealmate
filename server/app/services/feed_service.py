import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import MealPost, User
from app.services.post_service import load_cards
from app.utils.cursor import decode_cursor, encode_cursor
from app.utils.time import business_date, business_day_bounds

PAGE_SIZE = 20
MAX_PAGE_SIZE = 50
EARTH_RADIUS_M = 6_371_000


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lng / 2) ** 2
    return int(2 * EARTH_RADIUS_M * math.asin(math.sqrt(a)))


async def list_feed(
    db: AsyncSession,
    viewer: User | None,
    *,
    filter_type: str,
    cursor: str | None,
    limit: int,
    lat: float | None,
    lng: float | None,
    radius_m: int,
) -> dict[str, Any]:
    limit = min(max(limit, 1), MAX_PAGE_SIZE)
    start, end = business_day_bounds(business_date())

    conditions = [
        MealPost.status == "published",
        MealPost.published_at >= start,
        MealPost.published_at < end,
    ]

    cursor_data = decode_cursor(cursor)
    if cursor:
        published = _parse_dt(cursor_data.get("publishedAt") if cursor_data else None)
        cursor_id = cursor_data.get("id") if cursor_data else None
        if published is None or not cursor_id:
            raise AppError("CURSOR_INVALID", "分页游标无效，请刷新后重试")
        conditions.append(
            or_(
                MealPost.published_at < published,
                and_(MealPost.published_at == published, MealPost.id < cursor_id),
            )
        )

    distances: dict[str, int] = {}
    if filter_type == "near":
        if lat is None or lng is None:
            raise AppError("LOCATION_REQUIRED", "查看附近需要先授权粗略位置")
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise AppError("LOCATION_INVALID", "位置参数不正确")
        lat_delta = radius_m / 111_000
        lng_delta = radius_m / (111_000 * max(math.cos(math.radians(lat)), 0.01))
        conditions.extend(
            [
                MealPost.coarse_lat.is_not(None),
                MealPost.coarse_lat.between(lat - lat_delta, lat + lat_delta),
                MealPost.coarse_lng.between(lng - lng_delta, lng + lng_delta),
            ]
        )

    rows = (
        await db.scalars(
            select(MealPost)
            .where(*conditions)
            .order_by(MealPost.published_at.desc(), MealPost.id.desc())
            .limit(limit + 1)
        )
    ).all()

    has_more = len(rows) > limit
    page = rows[:limit]

    if filter_type == "near":
        for post in page:
            if post.coarse_lat is not None and post.coarse_lng is not None:
                distances[post.id] = _distance_m(lat, lng, post.coarse_lat, post.coarse_lng)

    items = await load_cards(db, page, viewer.id if viewer else None, distances)
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor(
            {"publishedAt": last.published_at.isoformat(), "id": last.id}
        )

    return {
        "filter": filter_type,
        "businessDate": business_date().isoformat(),
        "items": items,
        "nextCursor": next_cursor,
        "hasMore": has_more,
    }
