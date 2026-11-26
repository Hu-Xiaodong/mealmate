"""从知识库文档生成菜谱草稿。

为什么需要这个服务：
    运营上传的菜谱资料本质上就是“结构化菜谱”，如果只是切成向量供检索，
    菜谱列表仍然是空的。这个服务把同一份 Markdown 再解析一次，
    生成一条状态为“草稿”的菜谱，运营在菜谱管理里核对、补封面后发布。

为什么用固定模板解析，而不是把整篇丢给大模型：
    1. 文档模板固定（HowToCook 风格：一级标题 + 必备原料和工具 + 计算 + 操作 + 附加内容），
       按标题和列表解析的结果稳定、可测试，不花钱也不受模型波动影响；
    2. 生成的是草稿，不是直接发布，解析不准的地方由运营在后台修改；
    3. 真正格式混乱的资料才需要大模型抽取，那是后续可选的增强，不是第一版的前提。

和知识库的关系：
    一对一。一篇文档最多对应一条菜谱，用 source_type=kb_document、source_uri=文档编号
    记录来源；重复生成时更新草稿，已发布的菜谱不会被覆盖。
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import new_id
from app.db.models import AdminUser, Recipe
from app.db.rag_models import KbDocument
from app.services import howtocook_parser
from app.services.admin_recipe_service import sync_categories
from app.services.audit_service import write_audit
from app.services.storage import get_storage
from app.utils.time import now_utc

# 菜谱表字段长度限制，超过时直接给出可读错误，而不是让数据库报错。
MAX_TITLE_LENGTH = 40
MAX_INGREDIENTS = 30
MAX_STEPS = 30
# 一篇文档最多取多少张图片作为候选封面；再多也没有意义。
MAX_IMAGES = 10


def _pick_cover(image_paths: list[str]) -> str:
    """从文档引用的图片里挑一张作为菜谱封面。

    优先本服务保存的图片（地址以 /media/kb/ 开头），因为外链可能失效；
    没有本地图片时退回第一张外链图片；一张都没有就留空，
    草稿允许没有封面，运营发布前需要自己补。
    """
    for path in image_paths[:MAX_IMAGES]:
        if path.startswith("/media/kb/"):
            return path
    return image_paths[0] if image_paths else ""


def _parse_recipe(text_content: str, document: KbDocument) -> howtocook_parser.ParsedRecipe:
    """按固定模板解析文档正文。

    解析器复用 howtocook_parser：它只依赖标题和列表，不连接数据库，
    既能被命令行试运行使用，也能直接在这里复用，避免两套解析规则。
    """
    try:
        return howtocook_parser.parse_markdown(
            text_content, source_path=f"kb/{document.id}/{document.title}.md"
        )
    except howtocook_parser.ParseError as exc:
        raise AppError(
            "KB_RECIPE_TEMPLATE",
            f"文档不符合菜谱模板：{exc}",
            status_code=400,
        ) from exc


def _apply_draft(
    recipe: Recipe,
    parsed: howtocook_parser.ParsedRecipe,
    document: KbDocument,
) -> None:
    """把解析结果写进菜谱对象。

    只填能从文档稳定得到的字段：
    分类编码、口味、封面等需要人工判断的内容留空或使用原文，
    避免程序猜测后还要运营逐项改回来。
    """
    if len(parsed.title) > MAX_TITLE_LENGTH:
        raise AppError(
            "KB_RECIPE_TEMPLATE",
            f"菜名超过 {MAX_TITLE_LENGTH} 个字，请缩短一级标题",
            status_code=400,
        )
    if not parsed.ingredients:
        raise AppError(
            "KB_RECIPE_TEMPLATE",
            "没有识别到原料，请按模板写“## 必备原料和工具”并用列表列出",
            status_code=400,
        )
    if not parsed.steps:
        raise AppError(
            "KB_RECIPE_TEMPLATE",
            "没有识别到步骤，请按模板写“## 操作”并用编号列出",
            status_code=400,
        )
    if len(parsed.ingredients) > MAX_INGREDIENTS:
        raise AppError(
            "KB_RECIPE_TEMPLATE",
            f"原料超过 {MAX_INGREDIENTS} 条，请精简后再生成",
            status_code=400,
        )
    if len(parsed.steps) > MAX_STEPS:
        raise AppError(
            "KB_RECIPE_TEMPLATE",
            f"步骤超过 {MAX_STEPS} 条，请精简后再生成",
            status_code=400,
        )

    recipe.title = parsed.title
    recipe.cover_url = _pick_cover(parsed.image_paths)
    recipe.total_minutes = parsed.total_minutes
    # 工具编码沿用解析器的映射（wok、pot 等），与 AI 筛选使用的编码一致。
    recipe.tool_codes = parsed.tools
    # 文档里的目录名不能直接当客户端分类编码用，但也不能留空：
    # 客户端列表按分类筛选，没有分类关联的菜谱在任何分类下都查不到。
    # 因此新草稿默认归入“推荐”，运营核对时可以再改成快手、一锅等更精确的分类。
    recipe.category_codes = ["recommended"]
    recipe.servings = parsed.servings or 1
    recipe.main_ingredients = [item.name[:12] for item in parsed.ingredients[:3]]
    recipe.ingredients = [
        {"name": item.name[:40], "amount": (item.amount_text or "适量")[:40]}
        for item in parsed.ingredients
    ]
    recipe.steps = parsed.steps
    # 前置条件需要人工判断（例如“需要提前腌制”），不从文档猜。
    recipe.preconditions = None
    recipe.description = parsed.description or None
    recipe.tips = "\n".join(parsed.tips) if parsed.tips else None
    recipe.difficulty = parsed.difficulty or None
    tags = [parsed.category] if parsed.category not in ("", "unknown", "kb") else []
    recipe.tags = tags
    # 草稿：不发布、不标记为已验证，等运营核对。
    recipe.content_origin = "kb"
    recipe.validation_status = "pending"
    recipe.status = "draft"
    recipe.source_type = "kb_document"
    recipe.source_uri = document.id
    recipe.source_checksum = document.checksum
    recipe.import_batch_id = document.import_batch_id
    recipe.source_meta = {
        "documentId": document.id,
        "documentTitle": document.title,
        "warnings": parsed.warnings,
        "unknownTools": parsed.unknown_tools,
    }


async def generate_draft(
    db: AsyncSession,
    admin: AdminUser,
    document_id: str,
    ip: str | None = None,
) -> dict[str, Any]:
    """为一篇知识库文档生成或更新菜谱草稿。

    返回：
        {recipeId, title, created, skipped, message}

    幂等规则：
        同一篇文档重复生成时，如果已有菜谱还是草稿就更新它；
        已经发布或下架的菜谱不回写，避免覆盖运营手工修改的内容。
    """
    document = await db.get(KbDocument, document_id)
    if document is None:
        raise AppError("KB_DOCUMENT_NOT_FOUND", "文档不存在", status_code=404)

    raw = get_storage().read(document.storage_key)
    text_content = raw.decode("utf-8-sig")

    existing = await db.scalar(
        select(Recipe).where(
            Recipe.source_type == "kb_document",
            Recipe.source_uri == document.id,
        )
    )
    if existing is not None and existing.status != "draft":
        return {
            "recipeId": existing.id,
            "title": existing.title,
            "created": False,
            "skipped": True,
            "message": "该文档已有已发布或已下架的菜谱，未覆盖；如需重新生成请先在菜谱管理里处理",
        }

    parsed = _parse_recipe(text_content, document)
    if existing is None:
        recipe = Recipe(id=new_id("r"), created_at=now_utc())
        _apply_draft(recipe, parsed, document)
        db.add(recipe)
        action = "recipe.generate_draft"
        created = True
    else:
        recipe = existing
        _apply_draft(recipe, parsed, document)
        action = "recipe.regenerate_draft"
        created = False

    await db.flush()
    # 分类要同时写关联表：列表筛选走关联表，详情展示走 category_codes，
    # 只改其中一个会出现“详情有分类、列表查不到”的不一致。
    await sync_categories(db, recipe.id, recipe.category_codes)
    write_audit(
        db,
        actor=admin,
        action=action,
        target_type="recipe",
        target_id=recipe.id,
        after={"title": recipe.title, "status": recipe.status, "sourceUri": recipe.source_uri},
        ip=ip,
    )
    await db.commit()
    return {
        "recipeId": recipe.id,
        "title": recipe.title,
        "created": created,
        "skipped": False,
        "message": "已生成菜谱草稿，请到菜谱管理核对后发布" if created else "已更新菜谱草稿",
    }
