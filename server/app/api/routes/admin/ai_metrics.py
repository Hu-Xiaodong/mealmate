"""本地 AI 指标接口。

不依赖 Langfuse：直接聚合本地调用日志与评分表。
Langfuse 的指标接口仍保留，作为可选的第二数据源。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import AdminPrincipal, require_permission
from app.core.responses import ok
from app.db.session import get_db
from app.services.ai_metrics_service import local_metrics

router = APIRouter(prefix="/admin/ai-metrics", tags=["admin-ai-metrics"])


@router.get("")
async def metrics(
    days: int = Query(default=7, ge=1, le=30),
    principal: AdminPrincipal = Depends(require_permission("ai.log.read")),
    db: AsyncSession = Depends(get_db),
):
    """本地统计：调用量、错误率、延迟、Token、成本、评分与提示词版本。"""
    return ok(await local_metrics(db, days))
