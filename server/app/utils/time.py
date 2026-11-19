from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

BUSINESS_TZ = ZoneInfo("Asia/Shanghai")


def now_utc() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """SQLite 读回的时间可能是 naive，统一按 UTC 处理。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def business_date(moment: datetime | None = None) -> date:
    current = moment or now_utc()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(BUSINESS_TZ).date()


def business_day_bounds(day: date | None = None) -> tuple[datetime, datetime]:
    """返回某个 Asia/Shanghai 自然日的 UTC 起止时间（左闭右开）。"""
    target = day or business_date()
    start_local = datetime.combine(target, time.min, tzinfo=BUSINESS_TZ)
    end_local = datetime.combine(target + timedelta(days=1), time.min, tzinfo=BUSINESS_TZ)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)
