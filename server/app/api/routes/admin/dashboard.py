from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import AdminPrincipal, require_permission
from app.core.responses import ok
from app.db.session import get_db
from app.services.analytics_service import dashboard_summary

router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"])


@router.get("")
async def dashboard(
    days: int = Query(default=7, ge=1, le=30),
    principal: AdminPrincipal = Depends(require_permission("dashboard.read")),
    db: AsyncSession = Depends(get_db),
):
    """数据看板：用户、内容、待审核与埋点趋势。

    所有数字来自业务表与埋点表，不使用演示数据，
    避免后台展示“看起来很漂亮但不可核对”的指标。
    """
    return ok(await dashboard_summary(db, days))
