from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user_silent
from app.core.responses import ok
from app.db.models import User
from app.db.session import get_db
from app.schemas import AnalyticsBatchRequest
from app.services.analytics_service import ingest_events

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post("/events")
async def report_events(
    body: AnalyticsBatchRequest,
    viewer: User | None = Depends(get_optional_user_silent),
    db: AsyncSession = Depends(get_db),
):
    """批量接收客户端埋点。

    这个接口允许游客调用，因为浏览行为本身不需要登录。
    若请求携带有效令牌，后端会回填账号归属；令牌无效则按匿名处理，
    不返回 401，避免埋点失败影响正常使用。
    """
    data = await ingest_events(db, viewer.id if viewer else None, body.events)
    return ok(data, "已接收")
