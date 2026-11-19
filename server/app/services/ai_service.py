"""AI 网关 MVP。

当前为可验证的本地推荐器：只从已公开菜谱/饭帖中筛选，不生成不存在的资源。
接入真实模型时替换 `_generate`，保留配额、来源标识与推荐 ID 校验。
"""

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import new_id
from app.db.models import AIUsage, MealPost, Recipe, User
from app.schemas import AIChatRequest
from app.services.storage import object_url
from app.utils.time import business_date

TOOL_LABELS = {
    "wok": "炒锅",
    "pot": "汤锅/炖锅",
    "microwave": "微波炉",
    "rice_cooker": "电饭煲",
    "steamer": "蒸锅",
}


async def chat(
    db: AsyncSession,
    viewer: User | None,
    subject_ref: str,
    body: AIChatRequest,
) -> dict[str, Any]:
    if settings.ai_provider != "mock":
        raise AppError(
            "AI_PROVIDER_NOT_READY",
            "AI 服务尚未完成供应商接入，请先浏览现有内容",
            status_code=503,
        )

    limit = settings.user_ai_daily_limit if viewer else settings.guest_ai_daily_limit
    today: date = business_date()
    usage = await db.scalar(
        select(AIUsage).where(
            AIUsage.subject_ref == subject_ref, AIUsage.usage_date == today
        )
    )
    if usage is None:
        usage = AIUsage(id=new_id("au"), subject_ref=subject_ref, usage_date=today, count=0)
        db.add(usage)
    if usage.count >= limit:
        raise AppError(
            "AI_QUOTA_EXCEEDED",
            "今天的问答次数已用完，可以继续浏览饭帖和菜谱",
            status_code=429,
            data={"limit": limit, "used": usage.count},
        )
    usage.count += 1
    await db.commit()

    context_post = None
    if body.context_type == "post" and body.context_id:
        context_post = await db.get(MealPost, body.context_id)
        if context_post and context_post.status != "published":
            context_post = None

    recipes = (
        await db.scalars(select(Recipe).where(Recipe.status == "published"))
    ).all()
    selected, relaxed = _select_recipes(recipes, body)

    recommendations = [
        {
            "targetType": "recipe",
            "targetId": recipe.id,
            "title": recipe.title,
            "summary": recipe.preconditions or f"{recipe.total_minutes} 分钟可完成",
            "coverImage": object_url(recipe.cover_url),
            "reason": (
                "不完全满足你的条件，仅作为快手选择参考"
                if relaxed
                else _reason(recipe, body)
            ),
        }
        for recipe in selected
    ]

    text_parts: list[str] = []
    if context_post:
        text_parts.append(f"你正在看「{context_post.title}」。")
        if context_post.author_recipe:
            text_parts.append("作者已经把完整做法写在饭帖详情里，可以直接展开查看。")
        elif context_post.platform_recipe_id:
            text_parts.append("详情里已直接展示平台参考做法，并标明来源。")
        else:
            text_parts.append("这条饭帖没有可核实的做法，我不会凭图片补出一套菜谱。")

    conditions = _condition_text(body)
    if selected and not relaxed:
        text_parts.append(f"按{conditions}，先给你 {len(selected)} 道可验证的快手菜。")
    elif selected:
        text_parts.append(f"目前没有完全满足{conditions}的菜谱，下面几道可以放宽条件后参考。")
    else:
        text_parts.append(f"目前没有满足{conditions}的菜谱，可以适当放宽时间、器具或食材条件。")
    text_parts.append(
        "做法与耗时来自平台试做菜谱；AI 只做筛选和解释，不代表你的实际食材一定可食用。"
    )

    return {
        "conversationId": new_id("c"),
        "origin": "ai_reference",
        "message": "".join(text_parts),
        "recommendations": recommendations,
        "quota": {"limit": limit, "used": usage.count, "remaining": limit - usage.count},
    }


def _select_recipes(
    recipes: list[Recipe], body: AIChatRequest
) -> tuple[list[Recipe], bool]:
    constraints = body.constraints
    hard = []
    for recipe in recipes:
        if constraints.max_minutes and recipe.total_minutes > constraints.max_minutes:
            continue
        if constraints.tools and not set(recipe.tool_codes).issubset(set(constraints.tools)):
            continue
        haystack = " ".join(
            [recipe.title] + [item.get("name", "") for item in recipe.ingredients]
        )
        if constraints.avoid and any(word and word in haystack for word in constraints.avoid):
            continue
        if constraints.ingredients:
            matched = any(
                word and word in haystack for word in constraints.ingredients
            )
            if not matched:
                continue
        hard.append(recipe)

    hard.sort(key=lambda recipe: (recipe.total_minutes, recipe.id))
    if hard:
        return hard[:3], False

    fallback = sorted(recipes, key=lambda recipe: (recipe.total_minutes, recipe.id))[:2]
    return fallback, True


def _reason(recipe: Recipe, body: AIChatRequest) -> str:
    parts = [f"{recipe.total_minutes} 分钟"]
    tools = [TOOL_LABELS.get(code, code) for code in recipe.tool_codes]
    if tools:
        parts.append("、".join(tools))
    if recipe.preconditions:
        parts.append(recipe.preconditions)
    return " · ".join(parts)


def _condition_text(body: AIChatRequest) -> str:
    constraints = body.constraints
    parts = []
    if constraints.max_minutes:
        parts.append(f" {constraints.max_minutes} 分钟内")
    if constraints.tools:
        labels = [TOOL_LABELS.get(code, code) for code in constraints.tools]
        parts.append("只用 " + "、".join(labels))
    if constraints.ingredients:
        parts.append("现有食材 " + "、".join(constraints.ingredients))
    return "、".join(part.strip() for part in parts) or "你描述的条件"
