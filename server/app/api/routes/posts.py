import secrets

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_user
from app.api.serializers import iso
from app.core.config import settings
from app.core.errors import AppError
from app.core.responses import ok
from app.db.models import MealPost, MediaAsset, User
from app.db.session import get_db
from app.schemas import CreatePostRequest
from app.services.post_service import load_detail
from app.utils.time import now_utc

router = APIRouter(prefix="/posts", tags=["posts"])


@router.get("/{post_id}")
async def post_detail(
    post_id: str,
    viewer: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    post = await db.get(MealPost, post_id)
    if post is None or post.status != "published":
        raise AppError("POST_NOT_FOUND", "这条饭帖暂时无法查看", status_code=404)
    return ok(await load_detail(db, post, viewer))


@router.post("")
async def create_post(
    body: CreatePostRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=64),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.scalar(
        select(MealPost).where(
            MealPost.author_id == user.id, MealPost.client_request_id == idempotency_key
        )
    )
    if existing:
        return ok(_publish_result(existing), "已提交过相同内容")

    if len(set(body.image_asset_ids)) != len(body.image_asset_ids):
        raise AppError("IMAGE_DUPLICATED", "图片不能重复选择")

    assets = (
        await db.scalars(
            select(MediaAsset).where(
                MediaAsset.id.in_(body.image_asset_ids),
                MediaAsset.owner_id == user.id,
                MediaAsset.status == "ready",
            )
        )
    ).all()
    if len(assets) != len(body.image_asset_ids):
        raise AppError("IMAGE_NOT_OWNED", "图片不存在或不属于当前账号，请重新上传")

    publish = settings.auto_publish_posts
    post = MealPost(
        id=f"p_{secrets.token_hex(8)}",
        author_id=user.id,
        title=body.title,
        review=body.review,
        source=body.source,
        image_asset_ids=body.image_asset_ids,
        author_recipe=body.author_recipe.model_dump() if body.author_recipe else None,
        takeaway_store=body.takeaway_store,
        dine_in_address=body.dine_in_address,
        coarse_lat=body.location.lat if body.location else None,
        coarse_lng=body.location.lng if body.location else None,
        coarse_area=body.location.area if body.location else None,
        status="published" if publish else "pending_review",
        client_request_id=idempotency_key,
        published_at=now_utc() if publish else None,
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)
    return ok(_publish_result(post), "已发布" if publish else "已提交审核")


def _publish_result(post: MealPost) -> dict:
    return {
        "postId": post.id,
        "status": post.status,
        "publishedAt": iso(post.published_at),
        "reviewRequired": post.status == "pending_review",
    }
