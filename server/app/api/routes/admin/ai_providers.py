from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import AdminPrincipal, client_ip, require_permission
from app.core.responses import ok
from app.db.session import get_db
from app.schemas import AIProviderCreateRequest, AIProviderUpdateRequest
from app.services.admin_ai_provider_service import (
    create_provider,
    delete_provider,
    list_call_logs,
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
    limit: int = Query(default=50, ge=1, le=200),
    principal: AdminPrincipal = Depends(require_permission("ai.log.read")),
    db: AsyncSession = Depends(get_db),
):
    """最近调用日志，用于排查“哪个模型失败、错误码是什么”。"""
    return ok(
        await list_call_logs(
            db, status=status, provider_id=provider_id, limit=limit
        )
    )
