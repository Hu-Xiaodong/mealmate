"""提示词变量管理接口。

共用变量和专属变量放在同一张表，通过 scope 区分；
「变量管理」页可以按提示词筛选，但共用变量始终展示。

写操作需要 ai.config.write：变量会直接影响线上提示词，
和改模型配置、发布提示词属于同一风险级别。
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import AdminPrincipal, client_ip, require_permission
from app.core.errors import AppError
from app.core.responses import ok
from app.db.models import AIPromptVariable
from app.db.session import get_db
from app.schemas import PromptVariableSaveRequest
from app.services import prompt_service, prompt_variable_service
from app.services.audit_service import write_audit

router = APIRouter(prefix="/admin/prompt-variables", tags=["admin-prompt-variables"])


@router.get("")
async def list_prompt_variables(
    prompt_name: str | None = Query(default=None, max_length=80),
    principal: AdminPrincipal = Depends(require_permission("ai.log.read")),
    db: AsyncSession = Depends(get_db),
):
    """变量列表；传 promptName 时返回共用变量 + 该提示词的专属变量。"""
    if prompt_name and prompt_name not in prompt_service.PROMPT_DEFINITIONS:
        raise AppError("AI_PROMPT_UNKNOWN", "不支持的提示词名称", status_code=400)
    items = await prompt_variable_service.list_variables(
        db, prompt_name=prompt_name
    )
    return ok(
        {
            "items": items,
            "prompts": [
                {"name": name, "title": definition["title"]}
                for name, definition in prompt_service.PROMPT_DEFINITIONS.items()
            ],
        }
    )


@router.post("")
async def save_prompt_variable(
    body: PromptVariableSaveRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("ai.config.write")),
    db: AsyncSession = Depends(get_db),
):
    """新增或修改变量；同一个 Key 视为同一条。"""
    if body.scope == "prompt" and body.prompt_name not in prompt_service.PROMPT_DEFINITIONS:
        raise AppError("AI_PROMPT_UNKNOWN", "不支持的提示词名称", status_code=400)
    row = await prompt_variable_service.save_variable(
        db,
        scope=body.scope,
        prompt_name=body.prompt_name,
        key=body.key,
        value=body.value,
        default_value=body.default_value,
        author=(principal.admin.display_name or principal.admin.username),
    )
    write_audit(
        db,
        actor=principal.admin,
        action="ai_prompt_variable.save",
        target_type="ai_prompt_variable",
        target_id=row.id,
        after={
            "scope": row.scope,
            "promptName": row.prompt_name,
            "key": row.key,
            "value": row.value,
            "defaultValue": row.default_value,
        },
        ip=client_ip(request),
    )
    await db.commit()
    return ok(
        {
            "id": row.id,
            "key": row.key,
            "value": row.value,
            "defaultValue": row.default_value,
            "scope": row.scope,
            "promptName": row.prompt_name,
        },
        "变量已保存",
    )


@router.delete("/{variable_id}")
async def delete_prompt_variable(
    variable_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("ai.config.write")),
    db: AsyncSession = Depends(get_db),
):
    """删除变量；如果会让已发布提示词缺值，返回 409 并列出受影响提示词。"""
    row = await db.get(AIPromptVariable, variable_id)
    if row is None:
        raise AppError("AI_PROMPT_VARIABLE_NOT_FOUND", "变量不存在", status_code=404)
    snapshot = {
        "scope": row.scope,
        "promptName": row.prompt_name,
        "key": row.key,
        "value": row.value,
    }
    await prompt_variable_service.delete_variable(db, row)
    write_audit(
        db,
        actor=principal.admin,
        action="ai_prompt_variable.delete",
        target_type="ai_prompt_variable",
        target_id=variable_id,
        before=snapshot,
        ip=client_ip(request),
    )
    await db.commit()
    return ok({"id": variable_id}, "变量已删除")
