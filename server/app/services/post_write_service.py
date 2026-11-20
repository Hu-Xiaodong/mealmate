"""饭帖写入相关的业务逻辑：发布、存草稿、改草稿、发布草稿、删除。

把写操作集中在一个服务里，路由层只负责解析请求和返回响应。
这样做的好处是：发布和草稿共用同一套字段赋值逻辑，
不会出现“发布能存人均价格、存草稿却丢了”的偏差。
"""

import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import iso, media_url
from app.core.config import settings
from app.core.errors import AppError
from app.db.models import MealPost, MediaAsset, User
from app.schemas import CreatePostRequest, DraftPostRequest
from app.utils.time import now_utc

# 可以编辑或删除的状态：草稿、待审核、已发布、被拒绝、已被下架。
# deleted 不能再操作，避免重复删除把 deleted_at 覆盖掉。
EDITABLE_STATUSES = {"draft", "pending_review", "published", "rejected", "unpublished"}


async def validate_image_assets(
    db: AsyncSession, user_id: str, asset_ids: list[str]
) -> None:
    """校验图片编号是否合法、是否属于当前用户、是否已经处理完成。

    为什么要单独校验归属：
    图片编号会出现在请求体里，如果只信任客户端，别人就能把他人图片拼进自己的饭帖。
    这里同时检查 owner_id 与 status=ready，既防越权，也防引用尚未处理完的文件。
    """
    if not asset_ids:
        # 草稿允许没有图片，发布则由字段的 min_length=1 拦截。
        return
    if len(set(asset_ids)) != len(asset_ids):
        raise AppError("IMAGE_DUPLICATED", "图片不能重复选择")

    assets = (
        await db.scalars(
            select(MediaAsset).where(
                MediaAsset.id.in_(asset_ids),
                MediaAsset.owner_id == user_id,
                MediaAsset.status == "ready",
            )
        )
    ).all()
    if len(assets) != len(asset_ids):
        raise AppError("IMAGE_NOT_OWNED", "图片不存在或不属于当前账号，请重新上传")


def _apply_common_fields(
    post: MealPost,
    *,
    title: str,
    review: str,
    source: str,
    image_asset_ids: list[str],
    author_recipe: Any,
    takeaway_store: str | None,
    dine_in_address: str | None,
    location: Any,
    avg_price: int | None,
    taste_tags: list[str],
    store_location: Any,
) -> None:
    """把请求里的字段写到数据库对象上，发布与草稿共用。

    这里不提交事务，也不改状态。调用方决定是保存草稿还是正式发布。
    """
    post.title = title
    post.review = review
    post.source = source
    post.image_asset_ids = image_asset_ids
    post.author_recipe = author_recipe.model_dump() if author_recipe else None

    if source == "takeaway":
        post.takeaway_store = (takeaway_store or "").strip() or None
        post.dine_in_address = None
    elif source == "dine_in":
        post.dine_in_address = (dine_in_address or "").strip() or None
        post.takeaway_store = None
    else:
        post.takeaway_store = None
        post.dine_in_address = None

    post.avg_price = avg_price
    # 复制一份列表，避免和请求对象共享同一个可变列表。
    post.taste_tags = list(taste_tags)

    post.coarse_lat = location.lat if location else None
    post.coarse_lng = location.lng if location else None
    post.coarse_area = (location.area or "").strip() or None if location else None

    if source == "self":
        # 自己做饭没有店铺坐标，即使客户端传了也丢弃。
        post.store_lat = None
        post.store_lng = None
        post.store_poi_id = None
    else:
        post.store_lat = store_location.lat if store_location else None
        post.store_lng = store_location.lng if store_location else None
        post.store_poi_id = store_location.poi_id if store_location else None


async def create_post(
    db: AsyncSession,
    user: User,
    body: CreatePostRequest,
    *,
    client_request_id: str | None = None,
) -> MealPost:
    """直接发布一条饭帖。

    与旧版的区别只是多校验了图片、多了人均价格、口味标签与店铺坐标；
    状态仍由 AUTO_PUBLISH_POSTS 决定，演示环境直接发布，正式环境进入待审核。
    """
    await validate_image_assets(db, user.id, body.image_asset_ids)
    publish = settings.auto_publish_posts
    post = MealPost(
        id=f"p_{secrets.token_hex(8)}",
        author_id=user.id,
        title=body.title,
        review=body.review,
        source=body.source,
        image_asset_ids=body.image_asset_ids,
        status="published" if publish else "pending_review",
        # 幂等键只用于直接发布。草稿不写这个字段，
        # 否则同一个键先建草稿、再发布会被误判成“已经提交过”。
        client_request_id=client_request_id,
        published_at=now_utc() if publish else None,
    )
    _apply_common_fields(
        post,
        title=body.title,
        review=body.review,
        source=body.source,
        image_asset_ids=body.image_asset_ids,
        author_recipe=body.author_recipe,
        takeaway_store=body.takeaway_store,
        dine_in_address=body.dine_in_address,
        location=body.location,
        avg_price=body.avg_price,
        taste_tags=body.taste_tags,
        store_location=body.store_location,
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)
    return post


async def create_draft(db: AsyncSession, user: User, body: DraftPostRequest) -> MealPost:
    """保存一条草稿。

    草稿不要求图片、菜名、评价完整，用户可以先存一半，之后再回来继续写。
    但图片只要传了就必须属于当前用户，避免草稿阶段就出现越权引用。
    """
    await validate_image_assets(db, user.id, body.image_asset_ids)
    post = MealPost(
        id=f"p_{secrets.token_hex(8)}",
        author_id=user.id,
        title=body.title,
        review=body.review,
        source=body.source or "self",
        image_asset_ids=body.image_asset_ids,
        status="draft",
    )
    _apply_common_fields(
        post,
        title=body.title,
        review=body.review,
        source=body.source or "self",
        image_asset_ids=body.image_asset_ids,
        author_recipe=body.author_recipe,
        takeaway_store=body.takeaway_store,
        dine_in_address=body.dine_in_address,
        location=body.location,
        avg_price=body.avg_price,
        taste_tags=body.taste_tags,
        store_location=body.store_location,
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)
    return post


async def _owned_post(db: AsyncSession, user: User, post_id: str) -> MealPost:
    """取一条属于当前用户、且还可以操作的饭帖。

    不属于自己时统一返回 404，而不是 403。
    404 不会泄露“这个编号确实存在”，可以避免别人枚举内容。
    """
    post = await db.get(MealPost, post_id)
    if post is None or post.author_id != user.id or post.status not in EDITABLE_STATUSES:
        raise AppError("POST_NOT_FOUND", "饭帖不存在或已删除", status_code=404)
    return post


async def update_draft(
    db: AsyncSession, user: User, post_id: str, body: DraftPostRequest
) -> MealPost:
    """整体更新自己的草稿。

    使用 PUT 而不是 PATCH：客户端每次都提交完整的草稿内容，
    服务端直接覆盖，逻辑简单，也不会出现“字段没传就保持不变”的歧义。
    """
    post = await _owned_post(db, user, post_id)
    if post.status != "draft":
        raise AppError("POST_NOT_DRAFT", "只有草稿可以这样编辑", status_code=400)

    await validate_image_assets(db, user.id, body.image_asset_ids)
    _apply_common_fields(
        post,
        title=body.title,
        review=body.review,
        source=body.source or post.source,
        image_asset_ids=body.image_asset_ids,
        author_recipe=body.author_recipe,
        takeaway_store=body.takeaway_store,
        dine_in_address=body.dine_in_address,
        location=body.location,
        avg_price=body.avg_price,
        taste_tags=body.taste_tags,
        store_location=body.store_location,
    )
    await db.commit()
    await db.refresh(post)
    return post


async def publish_draft(
    db: AsyncSession, user: User, post_id: str, body: CreatePostRequest
) -> MealPost:
    """把草稿补全后正式发布。

    请求体使用完整的 CreatePostRequest，草稿本身不作为“已校验”的凭证。
    这样即使草稿存了半截内容，也无法绕过菜名、评价、图片等发布规则。
    """
    post = await _owned_post(db, user, post_id)
    if post.status != "draft":
        raise AppError("POST_NOT_DRAFT", "这条饭帖不是草稿，无需再次发布", status_code=400)

    await validate_image_assets(db, user.id, body.image_asset_ids)
    _apply_common_fields(
        post,
        title=body.title,
        review=body.review,
        source=body.source,
        image_asset_ids=body.image_asset_ids,
        author_recipe=body.author_recipe,
        takeaway_store=body.takeaway_store,
        dine_in_address=body.dine_in_address,
        location=body.location,
        avg_price=body.avg_price,
        taste_tags=body.taste_tags,
        store_location=body.store_location,
    )
    publish = settings.auto_publish_posts
    post.status = "published" if publish else "pending_review"
    post.published_at = now_utc() if publish else None
    await db.commit()
    await db.refresh(post)
    return post


async def delete_post(db: AsyncSession, user: User, post_id: str) -> MealPost:
    """作者删除自己的饭帖或草稿（软删除）。

    为什么软删除而不是 DELETE：
    1. 点赞、收藏、审核记录都引用这条饭帖，物理删除会产生悬空引用；
    2. 内容安全场景需要保留证据；
    3. 以后可以做“最近删除”恢复功能。
    公开列表都只查 status=published，所以软删除后内容立刻不可见。
    """
    post = await _owned_post(db, user, post_id)
    post.status = "deleted"
    post.deleted_at = now_utc()
    await db.commit()
    await db.refresh(post)
    return post


async def draft_payload(db: AsyncSession, post: MealPost) -> dict[str, Any]:
    """把草稿转换成编辑页需要的原始字段。

    不复用公开详情：详情会隐藏未发布内容、只返回图片地址，
    而编辑页需要 imageAssetIds 才能在不换图的情况下继续保存。

    图片地址必须与 imageAssetIds 一一对应：
    如果中间某张图片已经被清理，就在对应位置返回空字符串，
    不能把后面的图片往前挤，否则编辑页会把 A 图显示成 B 图。
    """
    asset_ids = post.image_asset_ids or []
    asset_urls = [""] * len(asset_ids)
    if asset_ids:
        rows = (
            await db.scalars(
                select(MediaAsset).where(
                    MediaAsset.id.in_(asset_ids), MediaAsset.status == "ready"
                )
            )
        ).all()
        url_by_id = {asset.id: media_url(asset.storage_key) for asset in rows}
        asset_urls = [url_by_id.get(asset_id, "") for asset_id in asset_ids]

    return {
        "postId": post.id,
        "title": post.title,
        "review": post.review,
        "source": post.source,
        "imageAssetIds": asset_ids,
        "images": asset_urls,
        "authorRecipe": post.author_recipe,
        "takeawayStore": post.takeaway_store,
        "dineInAddress": post.dine_in_address,
        "avgPrice": post.avg_price,
        "tasteTags": post.taste_tags,
        "location": (
            {
                "lat": post.coarse_lat,
                "lng": post.coarse_lng,
                "area": post.coarse_area,
            }
            if post.coarse_lat is not None and post.coarse_lng is not None
            else None
        ),
        "storeLocation": (
            {
                "lat": post.store_lat,
                "lng": post.store_lng,
                "poiId": post.store_poi_id,
            }
            if post.store_lat is not None and post.store_lng is not None
            else None
        ),
        "updatedAt": iso(post.updated_at),
    }
