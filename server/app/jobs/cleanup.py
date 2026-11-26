"""AI 数据每日清理任务。

运行方式（在 server 目录、激活虚拟环境后）：

    python -m app.jobs.cleanup

清理内容：
1. 超过 30 天没有活动的 AI 会话及其消息（登录用户）；
2. 所属用户已经不存在的孤儿会话（账号删除功能的兜底）；
3. 超过 180 天的 AI 调用日志与调用过程明细。

为什么聊天记录 30 天、日志 180 天：
- 聊天记录属于用户内容，长期保存会增加隐私与存储风险，
  产品也只承诺“最近一个月的历史”；
- 调用日志用于排障、成本核算和供应商评估，问题往往在几周后才暴露，
  保留半年才能覆盖常见的追溯周期；日志里不保存聊天正文，
  只保存模型、耗时、token 和错误码，隐私风险更低。

为什么不做成应用启动时的后台协程：
定时任务需要“每天固定跑一次、失败可重试、可手动补跑”，
放在 Web 进程里会随进程重启而丢失调度状态，多副本部署时还会重复执行。
用独立命令 + 操作系统定时器（cron、Windows 任务计划程序）最简单可靠，
以后任务变多再引入专业调度系统也不迟。
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import AICallLog, AICallTrace
from app.db.session import SessionLocal
from app.services.ai_history_service import (
    purge_expired_conversations,
    purge_orphan_conversations,
)
from app.utils.time import now_utc

logger = logging.getLogger("mealmate.cleanup")


async def purge_expired_call_logs(
    db: AsyncSession, retention_days: int | None = None
) -> dict[str, int]:
    """删除超过保留期的调用日志和过程明细。

    先删明细再删汇总，避免出现“汇总没了、明细还在”的孤儿数据。
    两张表都没有外键，删除顺序需要由代码保证。
    """
    days = retention_days or settings.ai_call_log_retention_days
    cutoff = now_utc() - timedelta(days=days)
    log_ids = (
        await db.scalars(select(AICallLog.id).where(AICallLog.created_at < cutoff))
    ).all()
    if not log_ids:
        # 汇总日志可能已经被手工清理过，但明细还在；
        # 按明细自己的创建时间再兜底删一次，避免孤儿明细永久占用空间。
        trace_result = await db.execute(
            delete(AICallTrace).where(AICallTrace.created_at < cutoff)
        )
        await db.commit()
        return {"callLogs": 0, "callTraces": int(trace_result.rowcount or 0)}

    trace_result = await db.execute(
        delete(AICallTrace).where(
            (AICallTrace.call_log_id.in_(log_ids))
            | (AICallTrace.created_at < cutoff)
        )
    )
    await db.execute(delete(AICallLog).where(AICallLog.id.in_(log_ids)))
    await db.commit()
    logger.info(
        "清理 AI 调用日志：%s 条日志、%s 条明细（早于 %s 天）",
        len(log_ids),
        trace_result.rowcount or 0,
        days,
    )
    return {"callLogs": len(log_ids), "callTraces": int(trace_result.rowcount or 0)}


async def run_cleanup() -> dict[str, int]:
    """执行一次完整清理，返回各表的删除数量。

    为什么要在一个命令里跑完三类清理：
    运维只需要配置一条每日任务，失败时也只需要排查一个入口；
    三类数据互不依赖，但都属于“过期 AI 数据”的同一件事。
    """
    async with SessionLocal() as db:
        expired_conversations = await purge_expired_conversations(db)
        orphan_conversations = await purge_orphan_conversations(db)
        logs = await purge_expired_call_logs(db)
    result = {
        "expiredConversations": expired_conversations,
        "orphanConversations": orphan_conversations,
        "callLogs": logs["callLogs"],
        "callTraces": logs["callTraces"],
    }
    logger.info("AI 数据清理完成：%s", result)
    return result


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    result = asyncio.run(run_cleanup())
    print(
        "清理完成："
        f"过期会话 {result['expiredConversations']} 段，"
        f"孤儿会话 {result['orphanConversations']} 段，"
        f"调用日志 {result['callLogs']} 条，"
        f"调用明细 {result['callTraces']} 条"
    )


if __name__ == "__main__":
    main()
