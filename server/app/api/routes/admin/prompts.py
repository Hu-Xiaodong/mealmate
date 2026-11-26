"""本地提示词版本管理接口。

这些接口不依赖 Langfuse：
- 列表、历史、发布全部读写本地 `ai_prompt_versions`；
- Langfuse 配置后，发布成功会把新版本镜像过去，失败只记录状态；
- 因此“没接观测平台就不能改提示词”这个问题不存在。
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import AdminPrincipal, client_ip, require_permission
from app.core.errors import AppError
from app.core.responses import ok
from app.db.session import get_db
from app.schemas import (
    PromptPreviewRequest,
    PromptPublishRequest,
    PromptRollbackRequest,
)
from app.services import langfuse_service, prompt_service
from app.services.audit_service import write_audit

router = APIRouter(prefix="/admin/prompts", tags=["admin-prompts"])


@router.get("")
async def prompts(
    principal: AdminPrincipal = Depends(require_permission("ai.log.read")),
    db: AsyncSession = Depends(get_db),
):
    """提示词列表：本地线上版本、正文、来源与历史版本号。"""
    return ok(await prompt_service.list_prompts(db))


@router.get("/{name}/versions")
async def prompt_versions(
    name: str,
    limit: int = Query(default=20, ge=1, le=50),
    principal: AdminPrincipal = Depends(require_permission("ai.log.read")),
    db: AsyncSession = Depends(get_db),
):
    """本地历史版本，包含正文、发布人、变更说明与镜像状态。"""
    return ok({"items": await prompt_service.list_versions(db, name, limit=limit)})


@router.post("/{name}/preview")
async def preview_prompt(
    name: str,
    body: PromptPreviewRequest,
    principal: AdminPrincipal = Depends(require_permission("ai.log.read")),
    db: AsyncSession = Depends(get_db),
):
    """预览变量替换结果；不保存、不发布。"""
    variables = (
        [item.model_dump() for item in body.variables]
        if body.variables is not None
        else None
    )
    return ok(
        await prompt_service.preview_prompt(
            db, name, body.content, variables=variables
        )
    )


@router.post("/{name}/rollback")
async def rollback_prompt(
    name: str,
    body: PromptRollbackRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("ai.config.write")),
    db: AsyncSession = Depends(get_db),
):
    """回滚到指定历史版本，内容和专属变量一起恢复。"""
    if name not in prompt_service.PROMPT_DEFINITIONS:
        raise AppError("AI_PROMPT_UNKNOWN", "不支持的提示词名称", status_code=400)
    row = await prompt_service.rollback_prompt(
        db,
        name,
        body.version,
        commit_message=body.commit_message,
        author=(principal.admin.display_name or principal.admin.username),
    )
    write_audit(
        db,
        actor=principal.admin,
        action="ai_prompt.rollback",
        target_type="ai_prompt",
        target_id=name,
        after={"version": row.version, "rollbackFrom": body.version},
        ip=client_ip(request),
    )
    await db.commit()
    mirror_version = await prompt_service.mirror_to_langfuse(db, row)
    if mirror_version is not None:
        await db.commit()
    return ok(
        {
            "name": name,
            "version": row.version,
            "rollbackFrom": body.version,
            "langfuseVersion": mirror_version,
            "langfuseConfigured": langfuse_service.configured(),
        },
        f"已回滚到 v{body.version}，并发布为 v{row.version}",
    )


@router.post("/{name}/publish")
async def publish_prompt(
    name: str,
    body: PromptPublishRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("ai.config.write")),
    db: AsyncSession = Depends(get_db),
):
    """发布本地新版本，并尽力镜像到 Langfuse。

    事务顺序：
    1. 写入新版本、替换专属变量、归档旧版本、写审计日志，一起提交；
    2. 提交后再请求 Langfuse 镜像。
    这样网络失败不会把本地发布一起回滚；镜像版本号只作为展示状态。
    """
    if name not in prompt_service.PROMPT_DEFINITIONS:
        raise AppError("AI_PROMPT_UNKNOWN", "不支持的提示词名称", status_code=400)
    variables = (
        [item.model_dump() for item in body.variables]
        if body.variables is not None
        else None
    )
    row = await prompt_service.publish_prompt(
        db,
        name,
        body.content,
        commit_message=body.commit_message,
        author=(principal.admin.display_name or principal.admin.username),
        variables=variables,
    )
    write_audit(
        db,
        actor=principal.admin,
        action="ai_prompt.publish",
        target_type="ai_prompt",
        target_id=name,
        after={
            "version": row.version,
            "source": "local",
            "variables": len(row.variables or []),
        },
        ip=client_ip(request),
    )
    await db.commit()

    mirror_version = await prompt_service.mirror_to_langfuse(db, row)
    if mirror_version is not None:
        await db.commit()
    return ok(
        {
            "name": name,
            "version": row.version,
            "labels": ["production"],
            "langfuseVersion": mirror_version,
            "langfuseConfigured": langfuse_service.configured(),
        },
        "提示词新版本已发布",
    )
