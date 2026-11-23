"""后台模型供应商配置与调用日志查询。

为什么模型配置要放在数据库，而不是环境变量：
1. 运营需要在后台新增、停用、调整优先级，不能每次改配置都重启服务；
2. 自动分配需要同时存在多个模型，环境变量只能表达一套配置；
3. 密钥必须加密保存、列表只展示掩码、变更必须留审计日志，
   这些能力都依赖数据库和后台权限体系。

密钥处理原则：
- 新增和修改时接收明文，立刻用 Fernet 加密后落库；
- 任何查询接口只返回掩码，绝不返回明文或密文；
- 编辑时留空表示“保留原密钥”，前端不需要回填，也就不会把密钥带进浏览器存储。
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import iso
from app.core.errors import AppError
from app.core.security import decrypt_secret, encrypt_secret, mask_secret, new_id
from app.db.models import AdminUser, AICallLog, AIProvider
from app.schemas import AIProviderCreateRequest, AIProviderUpdateRequest
from app.services.ai_service import probe_provider
from app.services.audit_service import write_audit
from app.utils.time import now_utc

MAX_LOG_LIMIT = 200


def _masked_key(provider: AIProvider) -> str:
    """把数据库中的密钥密文还原后只返回掩码。

    如果 SECRET_KEY 被更换，旧密文无法解密。此时不抛错、不泄露密文，
    只显示占位符，提示运营重新填写密钥即可。
    """
    try:
        return mask_secret(decrypt_secret(provider.api_key_encrypted))
    except Exception:  # noqa: BLE001 - 解密失败原因不重要，统一按“需要重填”处理
        return "******（无法解密，请重新填写）"


def _payload(provider: AIProvider) -> dict[str, Any]:
    """后台展示与编辑需要的字段，密钥只给掩码。"""
    return {
        "id": provider.id,
        "name": provider.name,
        "providerType": provider.provider_type,
        "kind": provider.kind,
        "dimensions": provider.dimensions,
        "baseUrl": provider.base_url,
        "apiKeyMasked": _masked_key(provider),
        "model": provider.model,
        "enabled": provider.enabled,
        "priority": provider.priority,
        "timeoutSeconds": provider.timeout_seconds,
        "maxOutputTokens": provider.max_output_tokens,
        "lastTestAt": iso(provider.last_test_at),
        "lastTestOk": provider.last_test_ok,
        "lastTestMessage": provider.last_test_message,
        "createdAt": iso(provider.created_at),
        "updatedAt": iso(provider.updated_at),
    }


def _snapshot(provider: AIProvider) -> dict[str, Any]:
    """审计快照刻意不包含密钥和密文。

    审计日志会被很多人查看，密钥哪怕加密后也不应该出现在这里；
    需要确认“是否换过钥匙”时，看 apiKeyMasked 是否变化即可。
    """
    return {
        "name": provider.name,
        "providerType": provider.provider_type,
        "kind": provider.kind,
        "dimensions": provider.dimensions,
        "baseUrl": provider.base_url,
        "model": provider.model,
        "enabled": provider.enabled,
        "priority": provider.priority,
        "timeoutSeconds": provider.timeout_seconds,
        "maxOutputTokens": provider.max_output_tokens,
    }


async def list_providers(db: AsyncSession) -> dict[str, Any]:
    """按优先级升序返回全部配置，停用的也返回，方便随时恢复。"""
    rows = (
        await db.scalars(
            select(AIProvider).order_by(
                AIProvider.priority, AIProvider.created_at, AIProvider.id
            )
        )
    ).all()
    return {"items": [_payload(provider) for provider in rows]}


async def _ensure_name_available(
    db: AsyncSession, name: str, exclude_id: str | None = None
) -> None:
    existing = await db.scalar(select(AIProvider).where(AIProvider.name == name))
    if existing is not None and existing.id != exclude_id:
        raise AppError("AI_PROVIDER_NAME_EXISTS", "该模型名称已存在", status_code=409)


async def create_provider(
    db: AsyncSession,
    admin: AdminUser,
    body: AIProviderCreateRequest,
    ip: str | None,
) -> dict[str, Any]:
    name = body.name.strip()
    await _ensure_name_available(db, name)
    provider = AIProvider(
        id=new_id("aip"),
        name=name,
        provider_type=body.provider_type,
        kind=body.kind,
        dimensions=body.dimensions,
        base_url=body.base_url.strip().rstrip("/"),
        api_key_encrypted=encrypt_secret(body.api_key.strip()),
        model=body.model.strip(),
        enabled=body.enabled,
        priority=body.priority,
        timeout_seconds=body.timeout_seconds,
        max_output_tokens=body.max_output_tokens,
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    db.add(provider)
    write_audit(
        db,
        actor=admin,
        action="ai_provider.create",
        target_type="ai_provider",
        target_id=provider.id,
        after=_snapshot(provider),
        ip=ip,
    )
    await db.commit()
    return _payload(provider)


async def update_provider(
    db: AsyncSession,
    admin: AdminUser,
    provider_id: str,
    body: AIProviderUpdateRequest,
    ip: str | None,
) -> dict[str, Any]:
    provider = await db.get(AIProvider, provider_id)
    if provider is None:
        raise AppError("AI_PROVIDER_NOT_FOUND", "模型配置不存在", status_code=404)

    # 必须在修改字段之前保存快照，否则 before 和 after 会变成同一份数据。
    before = _snapshot(provider)
    if body.name is not None:
        name = body.name.strip()
        await _ensure_name_available(db, name, exclude_id=provider.id)
        provider.name = name
    if body.provider_type is not None:
        provider.provider_type = body.provider_type
    if body.kind is not None:
        provider.kind = body.kind
    if body.dimensions is not None:
        provider.dimensions = body.dimensions
    if body.base_url is not None:
        provider.base_url = body.base_url.strip().rstrip("/")
    if body.model is not None:
        provider.model = body.model.strip()
    if body.enabled is not None:
        provider.enabled = body.enabled
    if body.priority is not None:
        provider.priority = body.priority
    if body.timeout_seconds is not None:
        provider.timeout_seconds = body.timeout_seconds
    if body.max_output_tokens is not None:
        provider.max_output_tokens = body.max_output_tokens
    # 空字符串表示“保留原密钥”，只有真正填写了新密钥才重新加密。
    if body.api_key and body.api_key.strip():
        provider.api_key_encrypted = encrypt_secret(body.api_key.strip())

    # 修改后统一校验用途与维度，避免出现“embedding 但维度为空/不是 1024”
    # 这种配置，否则知识库写入向量时才会失败，排查成本更高。
    if provider.kind == "embedding":
        if provider.dimensions is None:
            provider.dimensions = 1024
        elif provider.dimensions != 1024:
            raise AppError(
                "AI_PROVIDER_DIMENSION_INVALID",
                "嵌入模型维度必须为 1024，与知识库向量列保持一致",
                status_code=400,
            )
    else:
        provider.dimensions = None

    provider.updated_at = now_utc()

    write_audit(
        db,
        actor=admin,
        action="ai_provider.update",
        target_type="ai_provider",
        target_id=provider.id,
        before=before,
        after=_snapshot(provider),
        ip=ip,
    )
    await db.commit()
    return _payload(provider)


async def delete_provider(
    db: AsyncSession, admin: AdminUser, provider_id: str, ip: str | None
) -> dict[str, Any]:
    provider = await db.get(AIProvider, provider_id)
    if provider is None:
        raise AppError("AI_PROVIDER_NOT_FOUND", "模型配置不存在", status_code=404)
    before = _snapshot(provider)
    await db.delete(provider)
    write_audit(
        db,
        actor=admin,
        action="ai_provider.delete",
        target_type="ai_provider",
        target_id=provider_id,
        before=before,
        ip=ip,
    )
    await db.commit()
    return {"id": provider_id, "deleted": True}


async def test_provider(
    db: AsyncSession, admin: AdminUser, provider_id: str
) -> dict[str, Any]:
    """真实调用一次模型，验证地址、密钥、模型名和额度是否都正常。

    测试结果写回配置表，运营下次打开列表就能看到最近一次测试的时间与结论，
    不需要每次重新点一遍。
    """
    provider = await db.get(AIProvider, provider_id)
    if provider is None:
        raise AppError("AI_PROVIDER_NOT_FOUND", "模型配置不存在", status_code=404)

    result = await probe_provider(db, provider, f"admin:{admin.id}")
    provider.last_test_at = now_utc()
    provider.last_test_ok = bool(result["ok"])
    provider.last_test_message = str(result["message"])[:200]
    provider.updated_at = now_utc()
    await db.commit()
    return result


async def list_call_logs(
    db: AsyncSession,
    *,
    status: str | None,
    provider_id: str | None,
    limit: int,
) -> dict[str, Any]:
    """查询最近的模型调用日志。

    先做最简单的“最近若干条 + 状态/供应商筛选”：
    排查线上问题时最常用的是“最近失败的是哪个模型、错误码是什么”，
    复杂的时间范围与关键字检索等真正有需求时再加。
    """
    limit = min(max(limit, 1), MAX_LOG_LIMIT)
    conditions = []
    if status:
        conditions.append(AICallLog.status == status.strip())
    if provider_id:
        conditions.append(AICallLog.provider_id == provider_id.strip())

    rows = (
        await db.scalars(
            select(AICallLog)
            .where(*conditions)
            .order_by(AICallLog.created_at.desc(), AICallLog.id.desc())
            .limit(limit)
        )
    ).all()
    items = [
        {
            "id": log.id,
            "requestId": log.request_id,
            "subjectRef": log.subject_ref,
            "contextType": log.context_type,
            "providerId": log.provider_id,
            "providerName": log.provider_name,
            "model": log.model,
            "status": log.status,
            "latencyMs": log.latency_ms,
            "promptTokens": log.prompt_tokens,
            "completionTokens": log.completion_tokens,
            "totalTokens": log.total_tokens,
            "errorCode": log.error_code,
            "errorMessage": log.error_message,
            "createdAt": iso(log.created_at),
        }
        for log in rows
    ]
    return {"items": items}
