"""审计日志服务。

审计日志是“只追加”的操作流水：谁、什么时间、从哪里、对什么对象、
做了什么、为什么。它和业务变更必须在同一个数据库事务里提交，
否则会出现“内容改了但没有日志”或“有日志但内容没改”的不一致。
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import iso
from app.core.errors import AppError, request_id_ctx
from app.core.security import new_id
from app.db.models import AdminUser, AuditLog
from app.utils.cursor import decode_cursor, encode_cursor
from app.utils.time import now_utc

MAX_PAGE_SIZE = 50


def write_audit(
    db: AsyncSession,
    *,
    actor: AdminUser,
    action: str,
    target_type: str,
    target_id: str,
    reason: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditLog:
    """写入一条审计日志。

    Args:
        db: 数据库会话，调用方负责最终 commit。
        actor: 当前操作的管理员。
        action: 动作标识，例如 post.approve、user.ban。
        target_type: 对象类型，例如 meal_post、user。
        target_id: 对象标识。
        reason: 操作原因，拒绝、下架、封禁时必填。
        before: 变更前关键字段快照。
        after: 变更后关键字段快照。
        ip: 来源地址。
    Returns:
        已加入会话但尚未提交的 AuditLog 对象。
    Why:
        把日志写入封装成一个函数，保证所有后台操作记录的字段一致，
        不会出现某个接口忘记记录 requestId 或来源地址的情况。
    """
    log = AuditLog(
        id=new_id("aud"),
        actor_id=actor.id,
        actor_name=actor.display_name or actor.username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        before_json=before,
        after_json=after,
        ip=ip,
        request_id=request_id_ctx.get() or None,
        created_at=now_utc(),
    )
    db.add(log)
    return log


def _parse_dt(value: str | None) -> datetime | None:
    """把查询参数中的 ISO 时间字符串转换成带时区的时间。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def list_audit_logs(
    db: AsyncSession,
    *,
    actor_name: str | None,
    action: str | None,
    target_type: str | None,
    target_id: str | None,
    start_at: str | None,
    end_at: str | None,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    """按条件分页查询审计日志，只读。

    分页使用游标而不是页码。审计日志会持续追加，
    页码分页在数据插入后容易重复或漏行；游标固定在上一次的最后一条之后。
    """
    limit = min(max(limit, 1), MAX_PAGE_SIZE)
    conditions = []
    if actor_name:
        conditions.append(AuditLog.actor_name.contains(actor_name.strip()))
    if action:
        conditions.append(AuditLog.action == action.strip())
    if target_type:
        conditions.append(AuditLog.target_type == target_type.strip())
    if target_id:
        conditions.append(AuditLog.target_id == target_id.strip())

    start = _parse_dt(start_at)
    if start_at and start is None:
        raise AppError("TIME_RANGE_INVALID", "开始时间格式不正确")
    end = _parse_dt(end_at)
    if end_at and end is None:
        raise AppError("TIME_RANGE_INVALID", "结束时间格式不正确")
    if start is not None:
        conditions.append(AuditLog.created_at >= start)
    if end is not None:
        conditions.append(AuditLog.created_at <= end)

    cursor_data = decode_cursor(cursor)
    if cursor:
        created = _parse_dt(cursor_data.get("createdAt") if cursor_data else None)
        cursor_id = cursor_data.get("id") if cursor_data else None
        if created is None or not cursor_id:
            raise AppError("CURSOR_INVALID", "分页游标无效，请刷新后重试")
        conditions.append(
            or_(
                AuditLog.created_at < created,
                and_(AuditLog.created_at == created, AuditLog.id < cursor_id),
            )
        )

    rows = (
        await db.scalars(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    page = rows[:limit]

    items = [
        {
            "id": log.id,
            "actorId": log.actor_id,
            "actorName": log.actor_name,
            "action": log.action,
            "targetType": log.target_type,
            "targetId": log.target_id,
            "reason": log.reason,
            "before": log.before_json,
            "after": log.after_json,
            "ip": log.ip,
            "requestId": log.request_id,
            "createdAt": iso(log.created_at),
        }
        for log in page
    ]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor({"createdAt": last.created_at.isoformat(), "id": last.id})
    return {"items": items, "nextCursor": next_cursor, "hasMore": has_more}
