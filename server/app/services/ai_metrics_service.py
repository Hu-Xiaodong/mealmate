"""本地 AI 指标统计。

为什么要有本地统计：
    Langfuse 是可选接入，而“今天调用多少次、失败多少、花了多少钱、
    哪个提示词版本效果差”是运营每天都要看的信息，不能依赖外部服务。
    数据本来就已经写在 ai_call_logs / ai_call_scores 里，直接聚合即可。

为什么不用一条复杂 SQL 做所有事：
    调用量、延迟、错误率适合用数据库聚合；
    分位数（P95）在 PostgreSQL 和 SQLite 的写法不同；
    评分是另一张表。拆成几个小查询，逻辑清楚，也方便测试与替换。

数据量说明：
    中小项目每天几百到几万次调用，按天分组查 30 天完全够用。
    如果调用量继续增长，再把明细同步到 ClickHouse 等分析库，
    这里的接口形状可以保持不变，只换底层数据源。
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AICallLog, AICallScore
from app.utils.time import now_utc


def _dialect(db: AsyncSession) -> str:
    bind = db.get_bind()
    return bind.dialect.name if bind is not None else "sqlite"


async def _p95_latency(
    db: AsyncSession, cutoff: Any, dialect: str
) -> float:
    """计算 P95 延迟。

    P95 的含义：把这段时间的调用按耗时从短到长排列，
    95% 的调用快于这个值。它比平均值更能反映“用户偶尔遇到的慢请求”。

    为什么要分数据库写：
    PostgreSQL 有内置的 percentile_cont 函数；
    SQLite 没有，只能把耗时取出来在程序里算。当前数据量小，可以接受。
    """
    if dialect == "postgresql":
        value = await db.scalar(
            select(
                func.percentile_cont(0.95).within_group(AICallLog.latency_ms)
            ).where(AICallLog.created_at >= cutoff)
        )
        return round(float(value or 0), 1)
    rows = (
        await db.scalars(
            select(AICallLog.latency_ms)
            .where(AICallLog.created_at >= cutoff)
            .order_by(AICallLog.latency_ms)
        )
    ).all()
    if not rows:
        return 0.0
    index = min(len(rows) - 1, max(0, int(len(rows) * 0.95) - 1))
    return round(float(rows[index]), 1)


async def local_metrics(db: AsyncSession, days: int = 7) -> dict[str, Any]:
    """按天统计调用量、错误率、延迟、Token、成本、评分与提示词版本。"""
    days = max(1, min(days, 30))
    cutoff = now_utc() - timedelta(days=days)
    dialect = _dialect(db)

    totals = (
        await db.execute(
            select(
                func.count(AICallLog.id),
                func.sum(
                    case((AICallLog.status != "success", 1), else_=0)
                ),
                func.avg(AICallLog.latency_ms),
                func.sum(AICallLog.total_tokens),
                func.sum(AICallLog.cost_usd),
            ).where(AICallLog.created_at >= cutoff)
        )
    ).one()
    calls = int(totals[0] or 0)
    errors = int(totals[1] or 0)
    avg_latency = round(float(totals[2] or 0), 1)
    total_tokens = int(totals[3] or 0)
    total_cost = round(float(totals[4] or 0), 6)

    if dialect == "postgresql":
        day_expr = func.to_char(
            func.date_trunc("day", AICallLog.created_at), "YYYY-MM-DD"
        )
    else:
        day_expr = func.strftime("%Y-%m-%d", AICallLog.created_at)

    daily_rows = (
        await db.execute(
            select(
                day_expr.label("day"),
                func.count(AICallLog.id),
                func.sum(
                    case((AICallLog.status != "success", 1), else_=0)
                ),
                func.avg(AICallLog.latency_ms),
                func.sum(AICallLog.total_tokens),
                func.sum(AICallLog.cost_usd),
            )
            .where(AICallLog.created_at >= cutoff)
            .group_by(day_expr)
            .order_by(day_expr)
        )
    ).all()
    trend = [
        {
            "date": str(row[0]),
            "calls": int(row[1] or 0),
            "errors": int(row[2] or 0),
            "avgLatencyMs": round(float(row[3] or 0), 1),
            "totalTokens": int(row[4] or 0),
            "totalCost": round(float(row[5] or 0), 6),
        }
        for row in daily_rows
    ]

    score_row = (
        await db.execute(
            select(
                func.avg(AICallScore.score),
                func.count(AICallScore.id),
            ).where(AICallScore.created_at >= cutoff)
        )
    ).one()
    score_rows = (
        await db.execute(
            select(AICallScore.score, func.count(AICallScore.id))
            .where(AICallScore.created_at >= cutoff)
            .group_by(AICallScore.score)
            .order_by(AICallScore.score)
        )
    ).all()

    prompt_rows = (
        await db.execute(
            select(
                AICallLog.prompt_name,
                AICallLog.prompt_version,
                AICallLog.prompt_source,
                func.count(AICallLog.id),
                func.sum(
                    case((AICallLog.status != "success", 1), else_=0)
                ),
                func.avg(AICallLog.latency_ms),
                func.sum(AICallLog.cost_usd),
            )
            .where(
                AICallLog.created_at >= cutoff,
                AICallLog.prompt_name.is_not(None),
            )
            .group_by(
                AICallLog.prompt_name,
                AICallLog.prompt_version,
                AICallLog.prompt_source,
            )
            .order_by(func.count(AICallLog.id).desc())
            .limit(20)
        )
    ).all()

    return {
        "configured": True,
        "source": "local",
        "message": "",
        "rangeDays": days,
        "summary": {
            "calls": calls,
            "errors": errors,
            "errorRate": round(errors / calls, 4) if calls else 0,
            "avgLatencyMs": avg_latency,
            "p95LatencyMs": await _p95_latency(db, cutoff, dialect),
            "totalTokens": total_tokens,
            "totalCost": total_cost,
        },
        "trend": trend,
        "scores": {
            "count": int(score_row[1] or 0),
            "average": round(float(score_row[0] or 0), 2),
            "distribution": [
                {"score": int(row[0]), "count": int(row[1] or 0)}
                for row in score_rows
            ],
        },
        "prompts": [
            {
                "name": row[0],
                "version": row[1],
                "source": row[2],
                "calls": int(row[3] or 0),
                "errors": int(row[4] or 0),
                "avgLatencyMs": round(float(row[5] or 0), 1),
                "totalCost": round(float(row[6] or 0), 6),
            }
            for row in prompt_rows
        ],
    }
