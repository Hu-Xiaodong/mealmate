from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import AdminPrincipal, require_permission
from app.core.responses import ok
from app.db.session import get_db
from app.services.audit_service import list_audit_logs

router = APIRouter(prefix="/admin/audit-logs", tags=["admin-audit"])


@router.get("")
async def audit_logs(
    actor_name: str | None = Query(default=None, alias="actorName", max_length=40),
    action: str | None = Query(default=None, max_length=60),
    target_type: str | None = Query(default=None, alias="targetType", max_length=40),
    target_id: str | None = Query(default=None, alias="targetId", max_length=40),
    start_at: str | None = Query(default=None, alias="startAt"),
    end_at: str | None = Query(default=None, alias="endAt"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50, alias="pageSize"),
    principal: AdminPrincipal = Depends(require_permission("audit.read")),
    db: AsyncSession = Depends(get_db),
):
    """审计日志查询，只读。

    后台不提供修改和删除接口；数据库层面也建议只给应用插入权限。
    """
    return ok(
        await list_audit_logs(
            db,
            actor_name=actor_name,
            action=action,
            target_type=target_type,
            target_id=target_id,
            start_at=start_at,
            end_at=end_at,
            page=page,
            page_size=page_size,
        )
    )
