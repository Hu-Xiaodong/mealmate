"""埋点事件入库与聚合。

职责边界：
1. 只接收 PRD 4.6 节定义过的事件名，未知事件直接丢弃，避免脏数据污染看板；
2. 以客户端 eventId 为主键做幂等，网络重试不会重复计数；
3. 账号归属由令牌解析，事件体里的任何账号字段都不采信；
4. 看板聚合按服务端接收时间统计，避免客户端时钟错误影响运营判断。
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnalyticsEvent, MealPost, User
from app.schemas import AnalyticsEventItem
from app.utils.time import as_utc, now_utc

# 与 PRD 4.6 节保持一致。新增事件必须先更新文档，再改这里。
ALLOWED_EVENTS = {
    "page_view",
    "gallery_change",
    "gallery_auto_state",
    "meal_impression",
    "meal_open",
    "recipe_open",
    "login_open",
    "verification_requested",
    "login_result",
    "pending_action_resumed",
    "like_result",
    "favorite_result",
    "publish_start",
    "source_change",
    "publish_result",
    "ai_open",
    "ai_hint_impression",
    "ai_hint_action",
    "ai_message_result",
    "ai_recommendation_open",
    "nearby_result",
    "client_error",
}

# 单条事件属性最多 4KB，防止客户端把整段页面文本或图片塞进来。
MAX_PROPERTIES_BYTES = 4096
# 客户端时间允许与服务端相差 7 天，超出范围一律按服务端时间记录。
MAX_CLOCK_SKEW = timedelta(days=7)


def _safe_time(value: datetime | None, now: datetime) -> datetime:
    if value is None:
        return now
    parsed = as_utc(value)
    if abs(parsed - now) > MAX_CLOCK_SKEW:
        return now
    return parsed


def _properties_ok(properties: dict[str, Any]) -> bool:
    try:
        raw = json.dumps(properties, ensure_ascii=False)
    except (TypeError, ValueError):
        return False
    return len(raw.encode("utf-8")) <= MAX_PROPERTIES_BYTES


async def ingest_events(
    db: AsyncSession,
    account_id: str | None,
    events: list[AnalyticsEventItem],
) -> dict[str, int]:
    """批量写入埋点。

    返回值区分 accepted / duplicated / rejected 三个计数，
    客户端可以据此判断是否需要重试，而不是盲目重发整批。
    """
    now = now_utc()
    accepted = duplicated = rejected = 0

    existing_ids = set(
        (
            await db.scalars(
                select(AnalyticsEvent.event_id).where(
                    AnalyticsEvent.event_id.in_([item.event_id for item in events])
                )
            )
        ).all()
    )

    for item in events:
        if item.event_name not in ALLOWED_EVENTS or not _properties_ok(item.properties):
            rejected += 1
            continue
        if item.event_id in existing_ids:
            duplicated += 1
            continue
        existing_ids.add(item.event_id)
        db.add(
            AnalyticsEvent(
                event_id=item.event_id,
                account_id=account_id,
                event_name=item.event_name,
                page_name=item.page_name,
                platform=item.platform,
                app_version=item.app_version,
                session_ref=item.session_ref,
                request_id=item.request_id,
                properties=item.properties,
                occurred_at=_safe_time(item.occurred_at, now),
                received_at=now,
            )
        )
        accepted += 1

    await db.commit()
    return {"accepted": accepted, "duplicated": duplicated, "rejected": rejected}


async def dashboard_summary(db: AsyncSession, days: int = 7) -> dict[str, Any]:
    """管理后台数据看板。

    统计口径：
    - 内容数直接查业务表，保证与审核列表一致；
    - 趋势按 analytics_events 的 received_at 聚合，服务端时间；
    - 漏斗只做事件计数，不推断“购买”或“真实吃过”。

    为什么不用一条复杂 SQL 完成：当前数据量小，清晰可读比极致性能重要；
    生产环境可把这段替换为定时汇总表或数据仓库查询。
    """
    days = min(max(days, 1), 30)
    today = now_utc().astimezone(UTC).date()
    start = datetime.combine(today - timedelta(days=days - 1), datetime.min.time(), tzinfo=UTC)

    user_total = int(await db.scalar(select(func.count(User.id))) or 0)
    user_new = int(
        await db.scalar(select(func.count(User.id)).where(User.created_at >= start)) or 0
    )
    post_total = int(
        await db.scalar(select(func.count(MealPost.id)).where(MealPost.status != "deleted"))
        or 0
    )
    post_pending = int(
        await db.scalar(
            select(func.count(MealPost.id)).where(MealPost.status == "pending_review")
        )
        or 0
    )
    post_published = int(
        await db.scalar(select(func.count(MealPost.id)).where(MealPost.status == "published"))
        or 0
    )
    post_today = int(
        await db.scalar(
            select(func.count(MealPost.id)).where(
                MealPost.published_at >= datetime.combine(
                    today, datetime.min.time(), tzinfo=UTC
                )
            )
        )
        or 0
    )

    event_rows = (
        await db.execute(
            select(AnalyticsEvent.event_name, func.count(AnalyticsEvent.event_id))
            .where(AnalyticsEvent.received_at >= start)
            .group_by(AnalyticsEvent.event_name)
        )
    ).all()
    event_counts = {name: int(count) for name, count in event_rows}

    # 按天分组需要数据库支持日期函数；为兼容 SQLite 测试与 PostgreSQL，
    # 这里取出时间戳后在 Python 中分桶，数据量小时足够。
    day_rows = (
        await db.scalars(
            select(AnalyticsEvent.received_at).where(AnalyticsEvent.received_at >= start)
        )
    ).all()
    trend_map: dict[str, dict[str, int]] = {}
    for offset in range(days):
        key = (start + timedelta(days=offset)).date().isoformat()
        trend_map[key] = {"date": key, "events": 0}

    for received in day_rows:
        key = as_utc(received).date().isoformat()
        if key in trend_map:
            trend_map[key]["events"] += 1

    return {
        "rangeDays": days,
        "users": {"total": user_total, "newInRange": user_new},
        "posts": {
            "total": post_total,
            "pending": post_pending,
            "published": post_published,
            "publishedToday": post_today,
        },
        "events": {
            "total": sum(event_counts.values()),
            "byName": event_counts,
        },
        "trend": [trend_map[key] for key in sorted(trend_map)],
    }
