"""提示词版本管理（本地数据库为准，Langfuse 可选镜像）。

为什么提示词不能只放在 Langfuse：
    提示词是核心业务配置，不是“观测附属品”。如果只有接了 Langfuse
    才能改提示词，那么没配置、网络不通、Langfuse 故障时，提示词就只能
    改代码发版。中小公司的常见做法是“自己的数据库/配置中心为主，
    观测平台只做镜像和对比”，本项目采用同样的思路。

版本规则：
    - 每次发布新增一行，旧版本不修改，历史永远可追溯；
    - 同一名称同时只有一行 status=production；
    - 回滚用“旧内容发布成新版本”实现，避免破坏历史；
    - Langfuse 配置后会把新版本镜像过去，失败不影响本地发布。

运行时读取顺序：
    1. 本地 production 版本；
    2. 本地没有时，尝试 Langfuse 的 production 版本；
    3. 都没有或读取失败，使用代码默认值。

缓存：
    每轮问答都查一次数据库虽然不慢，但完全没必要。这里缓存五分钟，
    发布时主动清缓存，单实例立即可见；多实例部署时其他实例最多等五分钟。
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import new_id
from app.db.models import AIPromptVersion
from app.services import langfuse_service, prompt_variable_service

logger = logging.getLogger("mealmate.prompts")

# 允许在后台版本管理的提示词。只开放代码里真正会读取的几项，
# 避免有人误建任意名字的提示词，改了却不生效。
PROMPT_DEFINITIONS: dict[str, dict[str, str]] = {
    "mealmate.chat.system": {
        "title": "非流式对话提示词（JSON 输出）",
        "description": (
            "仅当客户端调用 POST /ai/chat 时使用；App 默认走流式接口，"
            "本项用于旧客户端或流式接口不可用时的兜底。要求模型只返回 JSON，"
            "并限制菜谱编号来源。"
        ),
    },
    "mealmate.chat.stream.system": {
        "title": "流式对话提示词（标签格式）",
        "description": "流式问答使用；用 <reply> 与 <recipes> 标签边生成边解析。",
    },
    "mealmate.history.summary.system": {
        "title": "历史压缩提示词",
        "description": "会话历史达到模型窗口 60% 时，把旧对话合并成摘要。",
    },
}


@dataclass
class PromptSnapshot:
    """一次读取到的提示词及其来源。"""

    key: str
    text: str
    # 本地或 Langfuse 的版本号；代码默认值为 None。
    version: int | None
    # local 本地数据库；langfuse 远端；default 代码默认值。
    source: str
    # 发布时没有解析到的变量 Key；正常发布不会出现，留作运行时兜底告警。
    missing_keys: list[str] = field(default_factory=list)
    # 本次实际使用的变量值，便于调用日志排查“到底是哪个值”。
    variables: dict[str, str] = field(default_factory=dict)


def _default_text(key: str) -> str:
    """取代码里的默认提示词。

    延迟导入 ai_service：ai_service 需要导入本模块读取提示词，
    如果本模块在顶层再导入 ai_service 就会形成循环依赖。
    """
    from app.services import ai_service

    mapping = {
        "mealmate.chat.system": ai_service.SYSTEM_PROMPT,
        "mealmate.chat.stream.system": ai_service.STREAM_SYSTEM_PROMPT,
        "mealmate.history.summary.system": ai_service.SUMMARY_SYSTEM_PROMPT,
    }
    return mapping.get(key, "")


def _parse_text(data: dict[str, Any]) -> str:
    """从 Langfuse 返回的提示词对象里取出正文。"""
    prompt = data.get("prompt")
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, list):
        parts: list[str] = []
        for item in prompt:
            if isinstance(item, dict):
                content = item.get("content")
                if isinstance(content, str):
                    parts.append(content)
        return "\n".join(parts)
    return ""


# 缓存：提示词名称 -> (过期时间戳, 快照)
_cache: dict[str, tuple[float, PromptSnapshot]] = {}


def invalidate(key: str | None = None) -> None:
    """清缓存。发布后调用，保证当前实例立即使用新版本。"""
    if key is None:
        _cache.clear()
    else:
        _cache.pop(key, None)


async def _load_local_production(
    db: AsyncSession, key: str
) -> AIPromptVersion | None:
    """读取本地线上版本。"""
    return await db.scalar(
        select(AIPromptVersion)
        .where(
            AIPromptVersion.name == key,
            AIPromptVersion.status == "production",
        )
        .order_by(AIPromptVersion.version.desc())
        .limit(1)
    )


def default_text(key: str) -> str:
    """返回代码里的默认提示词，供变量删除检查等场景复用。"""
    return _default_text(key)


async def get_prompt(db: AsyncSession, key: str) -> PromptSnapshot:
    """读取线上提示词并完成变量替换。

    读取顺序：本地数据库 > Langfuse > 代码默认值。
    无论正文来自哪里，都使用同一套变量解析逻辑，保证预览和真实发送一致。

    失败时不抛异常，最多多等一次数据库查询或一次网络请求。
    问答主流程不能因为提示词版本读取失败而中断。
    """
    default = _default_text(key)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and cached[0] > now:
        return cached[1]

    raw_text = default
    version: int | None = None
    source = "default"
    try:
        row = await _load_local_production(db, key)
    except Exception:  # noqa: BLE001 - 数据库异常时仍应使用默认值
        logger.exception("读取本地提示词 %s 失败", key)
        row = None
    if row is not None:
        raw_text = row.content
        version = row.version
        source = "local"
    elif langfuse_service.configured():
        try:
            data = await langfuse_service.fetch_prompt(key, label="production")
            remote_text = _parse_text(data)
            if remote_text.strip():
                remote_version = data.get("version")
                raw_text = remote_text
                version = remote_version if isinstance(remote_version, int) else None
                source = "langfuse"
        except langfuse_service.LangfuseError as exc:
            logger.warning("读取 Langfuse 提示词 %s 失败：%s", key, exc.message)

    try:
        if source == "local" and row is not None:
            # 线上版本使用发布时的专属变量快照，而不是变量表里的草稿。
            # 这样在变量管理页修改专属变量后，必须重新发布才会影响线上。
            rendered = await prompt_variable_service.render_with_overrides(
                db, key, raw_text, row.variables or []
            )
        else:
            rendered = await prompt_variable_service.render(db, key, raw_text)
        text = rendered.text
        missing_keys = rendered.missing_keys
        variables = rendered.values
    except Exception:  # noqa: BLE001 - 变量解析失败时退回原文，不阻塞问答
        logger.exception("解析提示词 %s 的变量失败", key)
        text = raw_text
        missing_keys = []
        variables = {}
    if missing_keys:
        # 发布时已拦截缺失变量；这里出现说明数据库被手工改动或迁移未执行。
        logger.warning("提示词 %s 存在未解析变量：%s", key, ", ".join(missing_keys))

    snapshot = PromptSnapshot(
        key=key,
        text=text,
        version=version,
        source=source,
        missing_keys=missing_keys,
        variables=variables,
    )
    _cache[key] = (now + max(settings.langfuse_prompt_cache_seconds, 10), snapshot)
    return snapshot


async def list_prompts(db: AsyncSession) -> dict[str, Any]:
    """后台提示词列表：当前线上版本、正文、来源与本地历史版本号。"""
    rows = (
        await db.scalars(
            select(AIPromptVersion)
            .where(AIPromptVersion.name.in_(list(PROMPT_DEFINITIONS)))
            .order_by(AIPromptVersion.version.desc())
        )
    ).all()
    by_name: dict[str, list[AIPromptVersion]] = {}
    for row in rows:
        by_name.setdefault(row.name, []).append(row)

    items: list[dict[str, Any]] = []
    for key, definition in PROMPT_DEFINITIONS.items():
        versions = by_name.get(key, [])
        production = next(
            (row for row in versions if row.status == "production"), None
        )
        snapshot = await get_prompt(db, key)
        # 编辑器要看到带 {{key}} 的原文，不能直接用渲染后的正文，
        # 否则维护者一保存就会把变量值固化成普通文字。
        if production is not None:
            raw_content = production.content
        elif snapshot.source == "langfuse":
            # Langfuse 的原文没有在本地落库，只能展示已经渲染的版本。
            raw_content = snapshot.text
        else:
            raw_content = _default_text(key)
        if production is not None:
            # 列表预览展示线上效果，使用发布快照；编辑器里的专属变量仍是草稿。
            rendered = await prompt_variable_service.render_with_overrides(
                db, key, raw_content, production.variables or []
            )
        else:
            rendered = await prompt_variable_service.render(db, key, raw_content)
        specific_variables = await prompt_variable_service.snapshot_prompt_variables(
            db, key
        )
        items.append(
            {
                "name": key,
                "title": definition["title"],
                "description": definition["description"],
                "version": snapshot.version,
                "source": snapshot.source,
                "content": raw_content,
                "preview": rendered.text,
                "missingKeys": rendered.missing_keys,
                "variables": specific_variables,
                "versions": [row.version for row in versions],
                "updatedAt": production.created_at if production else None,
                "langfuseVersion": production.langfuse_version
                if production
                else None,
            }
        )
    return {
        "configured": langfuse_service.configured(),
        "warning": "",
        "items": items,
    }


async def list_versions(
    db: AsyncSession, key: str, *, limit: int = 20
) -> list[dict[str, Any]]:
    """查看某个提示词的本地历史版本正文。"""
    if key not in PROMPT_DEFINITIONS:
        return []
    rows = (
        await db.scalars(
            select(AIPromptVersion)
            .where(AIPromptVersion.name == key)
            .order_by(AIPromptVersion.version.desc())
            .limit(max(1, min(limit, 50)))
        )
    ).all()
    return [
        {
            "version": row.version,
            "content": row.content,
            "labels": ["production"] if row.status == "production" else [],
            "createdAt": row.created_at,
            "createdBy": row.created_by,
            "commitMessage": row.commit_message,
            "langfuseVersion": row.langfuse_version,
            # 专属变量随版本一起发布，历史里也展示快照，回滚时按它恢复。
            "variables": row.variables or [],
        }
        for row in rows
    ]


async def preview_prompt(
    db: AsyncSession,
    key: str,
    content: str | None,
    *,
    variables: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """预览变量替换结果，和真实发送使用同一个解析函数。"""
    if key not in PROMPT_DEFINITIONS:
        raise AppError("AI_PROMPT_UNKNOWN", "不支持的提示词名称", status_code=400)
    if content is None:
        row = await _load_local_production(db, key)
        content = row.content if row is not None else _default_text(key)
    rendered = await prompt_variable_service.render_with_overrides(
        db, key, content, variables
    )
    return {
        "name": key,
        "content": rendered.text,
        "missingKeys": rendered.missing_keys,
        "values": rendered.values,
        "sources": rendered.sources,
    }


async def publish_prompt(
    db: AsyncSession,
    key: str,
    content: str,
    *,
    commit_message: str | None,
    author: str,
    variables: list[dict[str, Any]] | None = None,
) -> AIPromptVersion:
    """发布新的本地版本，并把旧版本改为归档。

    variables 为编辑器提交的专属变量列表；
    None 表示沿用数据库里的专属变量（兼容旧客户端）。
    发布前会先解析正文，变量缺失时拒绝发布，避免线上发送带 {{key}} 的提示词。

    这里只做本地写入和 flush，不提交事务：
    路由层会把审计日志和版本写入放在同一个事务里，保证
    “发布了版本但没记审计”或“记了审计但版本没保存”都不会发生。
    """
    if key not in PROMPT_DEFINITIONS:
        raise langfuse_service.LangfuseError("不支持的提示词名称")
    if variables is not None:
        await prompt_variable_service.replace_prompt_variables(
            db, key, variables, author
        )
    rendered = await prompt_variable_service.render(db, key, content)
    if rendered.missing_keys:
        raise AppError(
            "AI_PROMPT_VARIABLE_MISSING",
            "提示词引用了没有值的变量："
            + "、".join(rendered.missing_keys)
            + "。请先补充专属变量或共用变量后再发布。",
            status_code=422,
            data={"missingKeys": rendered.missing_keys},
        )
    variable_snapshot = await prompt_variable_service.snapshot_prompt_variables(db, key)
    current_max = await db.scalar(
        select(func.max(AIPromptVersion.version)).where(
            AIPromptVersion.name == key
        )
    )
    await db.execute(
        update(AIPromptVersion)
        .where(
            AIPromptVersion.name == key,
            AIPromptVersion.status == "production",
        )
        .values(status="archived")
    )
    row = AIPromptVersion(
        id=new_id("aip"),
        name=key,
        version=int(current_max or 0) + 1,
        content=content,
        status="production",
        commit_message=(commit_message or "").strip() or None,
        created_by=author[:80],
        variables=variable_snapshot,
    )
    db.add(row)
    await db.flush()
    invalidate(key)
    return row


async def rollback_prompt(
    db: AsyncSession,
    key: str,
    version: int,
    *,
    commit_message: str | None,
    author: str,
) -> AIPromptVersion:
    """把旧版本内容与专属变量一起恢复，并发布成新版本。

    不直接修改历史行的 status：历史是只读的，
    回滚同样通过“新增一个版本”实现，这样任何一次线上变更都能追溯。
    """
    target = await db.scalar(
        select(AIPromptVersion).where(
            AIPromptVersion.name == key,
            AIPromptVersion.version == version,
        )
    )
    if target is None:
        raise AppError(
            "AI_PROMPT_VERSION_NOT_FOUND",
            f"提示词 {key} 不存在版本 v{version}",
            status_code=404,
        )
    return await publish_prompt(
        db,
        key,
        target.content,
        commit_message=(commit_message or "").strip() or f"回滚到 v{version}",
        author=author,
        variables=target.variables or [],
    )


async def mirror_to_langfuse(
    db: AsyncSession, row: AIPromptVersion
) -> int | None:
    """把本地版本镜像到 Langfuse，并把远端版本号记回本地。

    镜像失败不影响本地发布，只记录警告；下次发布时会继续尝试。
    这里不重试历史版本，避免一次网络故障导致后台长时间卡住。
    """
    if not langfuse_service.configured():
        return None
    try:
        data = await langfuse_service.create_prompt(
            row.name,
            row.content,
            labels=["production"],
            commit_message=row.commit_message,
        )
    except langfuse_service.LangfuseError as exc:
        logger.warning("提示词 %s 镜像到 Langfuse 失败：%s", row.name, exc.message)
        return None
    version = data.get("version")
    if isinstance(version, int):
        row.langfuse_version = version
        db.add(row)
        await db.flush()
        return version
    return None
