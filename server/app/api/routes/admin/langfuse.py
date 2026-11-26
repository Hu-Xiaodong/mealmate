"""管理后台的 Langfuse 观测接口（可选）。

这里只保留 Langfuse 专属能力：
1. 连接状态；
2. 作为第二数据源的指标查询。

提示词版本、评分等核心能力已经改为本地优先，分别放在
`admin/prompts.py` 和调用日志路由里，不依赖 Langfuse。

为什么由后端代理 Langfuse 接口：
- 私钥权限很高，绝不能下发到浏览器；
- 后台已有登录与权限体系，代理后可以统一鉴权；
- 海外服务在部分网络环境不稳定，后端可以统一加超时与降级提示。
"""

from fastapi import APIRouter, Depends, Query

from app.api.admin_deps import AdminPrincipal, require_permission
from app.core.responses import ok
from app.services import langfuse_service

router = APIRouter(prefix="/admin/langfuse", tags=["admin-langfuse"])


@router.get("/status")
async def status(
    principal: AdminPrincipal = Depends(require_permission("ai.log.read")),
):
    """查看 Langfuse 是否配置、能否连通。"""
    return ok(await langfuse_service.health())


@router.get("/metrics")
async def metrics(
    days: int = Query(default=7, ge=1, le=30),
    principal: AdminPrincipal = Depends(require_permission("ai.log.read")),
):
    """Langfuse 指标，作为本地统计之外的第二数据源。"""
    return ok(await langfuse_service.fetch_metrics(days))
