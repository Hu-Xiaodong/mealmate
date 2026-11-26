from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import AdminPrincipal, client_ip, require_permission
from app.core.responses import ok
from app.db.session import get_db
from app.schemas import (
    AICallScoreRequest,
    AIProviderCreateRequest,
    AIProviderUpdateRequest,
)
from app.services.admin_ai_provider_service import (
    add_call_score,
    create_provider,
    delete_provider,
    get_call_log_detail,
    list_call_logs,
    list_call_scores,
    list_providers,
    test_provider,
    update_provider,
)

router = APIRouter(prefix="/admin/ai-providers", tags=["admin-ai-providers"])
logs_router = APIRouter(prefix="/admin/ai-call-logs", tags=["admin-ai-logs"])


@router.get("")
async def list_all(
    principal: AdminPrincipal = Depends(require_permission("ai.config.write")),
    db: AsyncSession = Depends(get_db),
):
    """返回全部模型配置，包含停用项，密钥只给掩码。"""
    return ok(await list_providers(db))


@router.post("")
async def create(
    body: AIProviderCreateRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("ai.config.write")),
    db: AsyncSession = Depends(get_db),
):
    return ok(
        await create_provider(db, principal.admin, body, client_ip(request)),
        "模型配置已新增",
    )


@router.put("/{provider_id}")
async def update(
    provider_id: str,
    body: AIProviderUpdateRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("ai.config.write")),
    db: AsyncSession = Depends(get_db),
):
    """编辑配置。apiKey 留空表示保留原密钥。"""
    return ok(
        await update_provider(
            db, principal.admin, provider_id, body, client_ip(request)
        ),
        "模型配置已保存",
    )


@router.delete("/{provider_id}")
async def remove(
    provider_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("ai.config.write")),
    db: AsyncSession = Depends(get_db),
):
    return ok(
        await delete_provider(db, principal.admin, provider_id, client_ip(request)),
        "模型配置已删除",
    )


@router.post("/{provider_id}/test")
async def test(
    provider_id: str,
    principal: AdminPrincipal = Depends(require_permission("ai.config.write")),
    db: AsyncSession = Depends(get_db),
):
    """真实调用一次模型，确认密钥、地址、模型名和额度是否可用。"""
    return ok(await test_provider(db, principal.admin, provider_id))


@logs_router.get("")
async def logs(
    status: str | None = Query(default=None, max_length=20),
    provider_id: str | None = Query(default=None, alias="providerId", max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    principal: AdminPrincipal = Depends(require_permission("ai.log.read")),
    db: AsyncSession = Depends(get_db),
):
    """模型调用日志，页码分页，用于排查“哪个模型失败、错误码是什么”。"""
    return ok(
        await list_call_logs(
            db,
            status=status,
            provider_id=provider_id,
            page=page,
            page_size=page_size,
        )
    )


@logs_router.get("/{log_id}")
async def log_detail(
    log_id: str,
    principal: AdminPrincipal = Depends(require_permission("ai.log.read")),
    db: AsyncSession = Depends(get_db),
):
    """返回一次模型调用的完整执行过程：提示词、原始输出、解析与校验结果。

    为什么单独做一个详情接口：
        列表只需要汇总字段，如果列表接口顺带返回明细，页面数据量会成倍增加；
        详情按编号精确查询，打开一条加载一条，列表和详情互不影响。
    """
    return ok(await get_call_log_detail(db, log_id))


@logs_router.get("/{log_id}/scores")
async def log_scores(
    log_id: str,
    principal: AdminPrincipal = Depends(require_permission("ai.log.read")),
    db: AsyncSession = Depends(get_db),
):
    """一次调用已有的人工评分，按时间倒序。"""
    return ok({"items": await list_call_scores(db, log_id)})


@logs_router.post("/{log_id}/scores")
async def score_log(
    log_id: str,
    body: AICallScoreRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("ai.eval.write")),
    db: AsyncSession = Depends(get_db),
):
    """给一次 AI 回答打 1-5 分并写评语。

    评分先保存到本地，再尽力同步 Langfuse；
    Langfuse 不可用时仍然返回成功，只是标记为未同步。
    """
    return ok(
        await add_call_score(
            db,
            principal.admin,
            log_id,
            score=body.score,
            comment=body.comment,
            ip=client_ip(request),
        ),
        "评分已保存",
    )
