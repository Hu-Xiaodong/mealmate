"""提示词变量：解析、预览、发布快照与删除保护。

为什么把变量单独拆一层：
1. 预览和真实发送必须用同一套替换逻辑，否则“后台看着对、线上却不同”；
2. 变量有共用和专属两种作用域，优先级、删除检查、版本快照都需要统一入口；
3. 解析逻辑只处理字符串，不依赖数据库和网络，便于单元测试。

优先级（同名 Key）：
    专属值 > 共用值 > 专属默认值 > 共用默认值 > 缺失

缺失的处理：
    - 发布时：列出缺失 Key 并拒绝发布；
    - 预览时：保留 {{key}} 原样，同时返回缺失列表，方便维护者定位；
    - 运行时：正常不会出现（发布已拦截），如果数据库被手工改动，
      保留占位符并记录警告，避免悄悄把空字符串发给模型。
"""

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import new_id
from app.db.models import AIPromptVariable, AIPromptVersion
from app.utils.time import now_utc

logger = logging.getLogger("mealmate.prompt_variables")

# 变量 Key 允许中文、英文、数字、下划线、点和短横线，不允许空格和花括号。
# 用 \w 而不是只允许 ASCII，是因为维护者可能写“最大菜谱数”这种中文 Key；
# 限制长度和排除花括号，避免和 {{ }} 语法本身冲突。
_KEY_RE = re.compile(r"^[\w.-]{1,80}$")
# 匹配 {{key}}，允许花括号内有空格，例如 {{ max_recipes }}。
_TOKEN_RE = re.compile(r"\{\{\s*([\w.-]{1,80})\s*\}\}")

# 首次初始化时写入的共用变量，和迁移脚本里的默认值保持一致。
# 这些值只是“默认配置”，不是后端硬编码限制：维护者可以在变量管理页改。
DEFAULT_SHARED_VARIABLES: list[tuple[str, str]] = [
    ("max_recipes", "3"),
    ("max_reply_chars", "200"),
    ("max_reason_chars", "30"),
    ("max_summary_chars", "300"),
]


@dataclass
class VariableMaps:
    """一次解析需要的两层变量。"""

    shared: dict[str, AIPromptVariable]
    specific: dict[str, AIPromptVariable]


@dataclass
class RenderResult:
    """解析结果：渲染后的正文、缺失 Key、实际取值来源。"""

    text: str
    missing_keys: list[str]
    values: dict[str, str]
    sources: dict[str, str]


def validate_key(key: str) -> str:
    """校验变量 Key，返回去掉首尾空白后的值。"""
    cleaned = (key or "").strip()
    if not _KEY_RE.fullmatch(cleaned):
        raise AppError(
            "AI_PROMPT_VARIABLE_KEY_INVALID",
            "变量 Key 只能包含中文、英文、数字、下划线、点和短横线，长度 1 到 80",
            status_code=400,
        )
    return cleaned


def extract_keys(content: str) -> list[str]:
    """按出现顺序提取正文里的变量 Key，重复只保留一次。"""
    keys: list[str] = []
    for match in _TOKEN_RE.finditer(content or ""):
        key = match.group(1)
        if key not in keys:
            keys.append(key)
    return keys


def _has_value(value: str | None) -> bool:
    """空字符串和纯空白都视为“没有提供值”。"""
    return bool(value and value.strip())


def _load_rows(rows: Iterable[AIPromptVariable]) -> dict[str, AIPromptVariable]:
    return {row.key: row for row in rows}


async def load_maps(
    db: AsyncSession, prompt_name: str | None
) -> VariableMaps:
    """读取共用变量和某个提示词的专属变量。"""
    shared = _load_rows(
        (
            await db.scalars(
                select(AIPromptVariable).where(AIPromptVariable.scope == "shared")
            )
        ).all()
    )
    specific: dict[str, AIPromptVariable] = {}
    if prompt_name:
        specific = _load_rows(
            (
                await db.scalars(
                    select(AIPromptVariable).where(
                        AIPromptVariable.scope == "prompt",
                        AIPromptVariable.prompt_name == prompt_name,
                    )
                )
            ).all()
        )
    return VariableMaps(shared=shared, specific=specific)


def resolve_with_maps(content: str, maps: VariableMaps) -> RenderResult:
    """用给定的变量集合替换正文里的 {{key}}。

    这是纯函数：不查数据库、不发网络请求。
    预览、发布校验、运行时读取都调用它，保证三处结果完全一致。
    """
    keys = extract_keys(content)
    if not keys:
        # 正文没有占位符就直接使用原文，不做任何字符串改写。
        return RenderResult(text=content, missing_keys=[], values={}, sources={})

    missing: list[str] = []
    values: dict[str, str] = {}
    sources: dict[str, str] = {}

    def pick(key: str) -> tuple[str, str] | None:
        specific = maps.specific.get(key)
        shared = maps.shared.get(key)
        if specific is not None and _has_value(specific.value):
            return specific.value, "prompt"
        if shared is not None and _has_value(shared.value):
            return shared.value, "shared"
        if specific is not None and _has_value(specific.default_value):
            return specific.default_value or "", "prompt_default"
        if shared is not None and _has_value(shared.default_value):
            return shared.default_value or "", "shared_default"
        return None

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        found = pick(key)
        if found is None:
            if key not in missing:
                missing.append(key)
            # 预览时保留占位符，维护者能直接看到缺了哪个变量。
            return match.group(0)
        value, source = found
        values[key] = value
        sources[key] = source
        return value

    text = _TOKEN_RE.sub(replace, content)
    return RenderResult(
        text=text, missing_keys=missing, values=values, sources=sources
    )


async def render(
    db: AsyncSession, prompt_name: str | None, content: str
) -> RenderResult:
    """读取变量并解析正文；没有占位符时不会查数据库。"""
    if not extract_keys(content):
        return RenderResult(text=content, missing_keys=[], values={}, sources={})
    maps = await load_maps(db, prompt_name)
    return resolve_with_maps(content, maps)


async def render_with_overrides(
    db: AsyncSession,
    prompt_name: str,
    content: str,
    overrides: list[dict[str, Any]] | None,
) -> RenderResult:
    """预览时使用编辑器中尚未保存的专属变量。

    overrides 为 None 表示沿用数据库里的专属变量；
    传空列表表示“这个提示词当前没有任何专属变量”，
    这样编辑器里删掉一行后预览会立即反映出来。
    """
    if not extract_keys(content):
        return RenderResult(text=content, missing_keys=[], values={}, sources={})
    maps = await load_maps(db, prompt_name)
    if overrides is not None:
        maps.specific = _rows_from_payload(prompt_name, overrides)
    return resolve_with_maps(content, maps)


def _rows_from_payload(
    prompt_name: str, payload: list[dict[str, Any]]
) -> dict[str, AIPromptVariable]:
    """把接口传入的变量列表转换成和数据库行同样形状的对象。

    只用于解析，不写入数据库；因此 id/时间字段可以留空。
    """
    rows: dict[str, AIPromptVariable] = {}
    for item in payload:
        key = validate_key(str(item.get("key", "")))
        if key in rows:
            raise AppError(
                "AI_PROMPT_VARIABLE_DUPLICATE",
                f"变量 Key 重复：{key}",
                status_code=400,
            )
        rows[key] = AIPromptVariable(
            id="",
            key=key,
            value=str(item.get("value", "") or ""),
            default_value=item.get("defaultValue") or item.get("default_value"),
            scope="prompt",
            prompt_name=prompt_name,
            updated_by="",
            created_at=now_utc(),
            updated_at=now_utc(),
        )
    return rows


async def list_variables(
    db: AsyncSession, *, prompt_name: str | None = None
) -> list[dict[str, Any]]:
    """变量管理页的列表：可按提示词筛选，但共用变量始终返回。"""
    query = select(AIPromptVariable).order_by(
        AIPromptVariable.scope, AIPromptVariable.prompt_name, AIPromptVariable.key
    )
    rows = (await db.scalars(query)).all()
    if prompt_name:
        rows = [
            row
            for row in rows
            if row.scope == "shared"
            or (row.scope == "prompt" and row.prompt_name == prompt_name)
        ]
    return [await _variable_payload(db, row) for row in rows]


async def _variable_payload(
    db: AsyncSession, row: AIPromptVariable
) -> dict[str, Any]:
    """给前端返回一条变量，附带“哪些线上提示词引用了它”。"""
    used_by: list[str] = []
    if row.scope == "prompt" and row.prompt_name:
        if await _published_uses_key(db, row.prompt_name, row.key):
            used_by = [row.prompt_name]
    elif row.scope == "shared":
        # 延迟导入：prompt_service 在顶层导入本模块，这里再顶层导入会循环。
        from app.services import prompt_service

        production = (
            await db.scalars(
                select(AIPromptVersion).where(AIPromptVersion.status == "production")
            )
        ).all()
        production_names: set[str] = set()
        for version in production:
            production_names.add(version.name)
            if row.key in extract_keys(version.content):
                used_by.append(version.name)
        # 没有本地发布版本的提示词使用代码默认值，也要算作引用，
        # 否则变量管理页会显示“暂无线上引用”，和删除保护结果不一致。
        for prompt_name in prompt_service.PROMPT_DEFINITIONS:
            if prompt_name in production_names:
                continue
            if row.key in extract_keys(prompt_service.default_text(prompt_name)):
                used_by.append(prompt_name)
    return {
        "id": row.id,
        "key": row.key,
        "value": row.value or "",
        "defaultValue": row.default_value,
        "scope": row.scope,
        "promptName": row.prompt_name,
        "updatedBy": row.updated_by,
        "updatedAt": row.updated_at,
        "usedBy": used_by,
    }


async def _published_uses_key(
    db: AsyncSession, prompt_name: str, key: str
) -> bool:
    content = await db.scalar(
        select(AIPromptVersion.content)
        .where(
            AIPromptVersion.name == prompt_name,
            AIPromptVersion.status == "production",
        )
        .order_by(AIPromptVersion.version.desc())
        .limit(1)
    )
    return content is not None and key in extract_keys(content)


async def save_variable(
    db: AsyncSession,
    *,
    scope: str,
    prompt_name: str | None,
    key: str,
    value: str,
    default_value: str | None,
    author: str,
) -> AIPromptVariable:
    """新增或更新一个变量（同一个 Key 视为同一条）。"""
    if scope not in {"shared", "prompt"}:
        raise AppError("AI_PROMPT_VARIABLE_SCOPE_INVALID", "变量类型不正确", status_code=400)
    key = validate_key(key)
    if scope == "prompt" and not prompt_name:
        raise AppError(
            "AI_PROMPT_VARIABLE_PROMPT_REQUIRED",
            "专属变量必须绑定一个提示词",
            status_code=400,
        )
    if scope == "shared":
        prompt_name = None

    query = select(AIPromptVariable).where(
        AIPromptVariable.scope == scope, AIPromptVariable.key == key
    )
    if scope == "prompt":
        query = query.where(AIPromptVariable.prompt_name == prompt_name)
    row = await db.scalar(query)
    now = now_utc()
    if row is None:
        row = AIPromptVariable(
            id=new_id("aiv"),
            key=key,
            value=value,
            default_value=default_value,
            scope=scope,
            prompt_name=prompt_name,
            updated_by=author[:80],
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.value = value
        row.default_value = default_value
        row.updated_by = author[:80]
        row.updated_at = now
    await db.flush()
    _invalidate_cache(scope, prompt_name)
    return row


async def replace_prompt_variables(
    db: AsyncSession,
    prompt_name: str,
    payload: list[dict[str, Any]],
    author: str,
) -> None:
    """用编辑器提交的列表整体替换某个提示词的专属变量。

    为什么是“整体替换”而不是逐条增删：
    编辑器里可能同时新增、修改、删除多行，整体替换和用户看到的列表一致，
    也不会出现“删了一行但数据库里还留着”的情况。
    """
    desired = _rows_from_payload(prompt_name, payload)
    existing = (
        await db.scalars(
            select(AIPromptVariable).where(
                AIPromptVariable.scope == "prompt",
                AIPromptVariable.prompt_name == prompt_name,
            )
        )
    ).all()
    existing_by_key = {row.key: row for row in existing}
    now = now_utc()
    for key, incoming in desired.items():
        row = existing_by_key.pop(key, None)
        if row is None:
            db.add(
                AIPromptVariable(
                    id=new_id("aiv"),
                    key=key,
                    value=incoming.value,
                    default_value=incoming.default_value,
                    scope="prompt",
                    prompt_name=prompt_name,
                    updated_by=author[:80],
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            row.value = incoming.value
            row.default_value = incoming.default_value
            row.updated_by = author[:80]
            row.updated_at = now
    for row in existing_by_key.values():
        await db.delete(row)
    await db.flush()
    _invalidate_cache("prompt", prompt_name)


async def snapshot_prompt_variables(
    db: AsyncSession, prompt_name: str
) -> list[dict[str, Any]]:
    """生成发布快照，随后写入 ai_prompt_versions.variables。"""
    rows = (
        await db.scalars(
            select(AIPromptVariable)
            .where(
                AIPromptVariable.scope == "prompt",
                AIPromptVariable.prompt_name == prompt_name,
            )
            .order_by(AIPromptVariable.key)
        )
    ).all()
    return [
        {
            "key": row.key,
            "value": row.value or "",
            "defaultValue": row.default_value,
        }
        for row in rows
    ]


async def restore_prompt_variables(
    db: AsyncSession,
    prompt_name: str,
    snapshot: list[dict[str, Any]] | None,
    author: str,
) -> None:
    """回滚时把专属变量恢复成目标版本发布时的状态。"""
    await replace_prompt_variables(db, prompt_name, snapshot or [], author)


def _snapshot_has_value(
    snapshot: list[dict[str, Any]] | None, key: str
) -> bool:
    """发布快照里是否有这个 Key 的值或默认值。"""
    for item in snapshot or []:
        if item.get("key") != key:
            continue
        if _has_value(item.get("value")) or _has_value(item.get("defaultValue")):
            return True
    return False


async def delete_blockers(
    db: AsyncSession, row: AIPromptVariable
) -> list[str]:
    """删除前检查：删除后哪些已发布提示词会缺值。

    线上运行时，专属变量使用发布快照，而不是变量表里的草稿。
    因此判断共用变量能否删除时，要看每个已发布版本的快照里有没有同名值；
    专属变量是草稿，删除它不会影响已发布版本，只有在该提示词还没有
    本地发布版本、仍在使用代码默认提示词时才需要检查。
    """
    # 延迟导入：prompt_service 在顶层导入本模块，这里再顶层导入会循环。
    from app.services import prompt_service

    production = (
        await db.scalars(
            select(AIPromptVersion).where(AIPromptVersion.status == "production")
        )
    ).all()
    production_names = {version.name for version in production}

    if row.scope == "prompt":
        if not row.prompt_name or row.prompt_name in production_names:
            # 已有线上版本：删除草稿不会影响线上，下次发布时会重新校验。
            return []
        default_content = prompt_service.default_text(row.prompt_name)
        if row.key not in extract_keys(default_content):
            return []
        shared = await db.scalar(
            select(AIPromptVariable).where(
                AIPromptVariable.scope == "shared",
                AIPromptVariable.key == row.key,
            )
        )
        if shared and (
            _has_value(shared.value) or _has_value(shared.default_value)
        ):
            return []
        return [row.prompt_name]

    blockers: list[str] = []
    for version in production:
        if row.key not in extract_keys(version.content):
            continue
        # 共用变量被删除后，专属变量快照里的同名值仍然可用。
        if _snapshot_has_value(version.variables, row.key):
            continue
        blockers.append(version.name)

    # 没有本地发布版本的提示词会使用代码默认值，也要检查默认正文。
    for prompt_name in prompt_service.PROMPT_DEFINITIONS:
        if prompt_name in production_names:
            continue
        if row.key in extract_keys(prompt_service.default_text(prompt_name)):
            blockers.append(prompt_name)
    return blockers


async def delete_variable(
    db: AsyncSession, row: AIPromptVariable
) -> None:
    """删除变量；如果会让线上提示词缺值，拒绝并返回受影响的提示词。"""
    blockers = await delete_blockers(db, row)
    if blockers:
        raise AppError(
            "AI_PROMPT_VARIABLE_IN_USE",
            "删除后会导致已发布提示词缺值，请先修改并发布这些提示词："
            + "、".join(sorted(set(blockers))),
            status_code=409,
            data={"prompts": sorted(set(blockers))},
        )
    scope = row.scope
    prompt_name = row.prompt_name
    await db.delete(row)
    await db.flush()
    _invalidate_cache(scope, prompt_name)


def _invalidate_cache(scope: str, prompt_name: str | None) -> None:
    """变量变化后清理提示词缓存，保证“保存后全局生效”。"""
    # 延迟导入：prompt_service 在顶层导入本模块，这里再顶层导入会循环。
    from app.services import prompt_service

    if scope == "shared":
        prompt_service.invalidate(None)
    elif prompt_name:
        prompt_service.invalidate(prompt_name)
