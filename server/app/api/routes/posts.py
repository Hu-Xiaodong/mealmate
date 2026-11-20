"""饭帖接口：公开详情、直接发布、草稿保存与发布、作者删除。

写操作统一交给 post_write_service，路由只处理参数与响应，
方便把同一套字段校验复用到“直接发布”和“草稿发布”两个入口。
"""

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_user
from app.api.serializers import iso
from app.core.errors import AppError
from app.core.responses import ok
from app.db.models import MealPost, User
from app.db.session import get_db
from app.schemas import CreatePostRequest, DraftPostRequest
from app.services.post_service import load_detail
from app.services.post_write_service import (
    create_draft,
    create_post,
    delete_post,
    publish_draft,
    update_draft,
)

router = APIRouter(prefix="/posts", tags=["posts"])


@router.get("/{post_id}")
async def post_detail(
    post_id: str,
    viewer: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    # 公开详情只允许看已发布的饭帖。
    # 草稿、待审核、被拒绝、已删除都统一返回 404，
    # 不向作者以外的人泄露“这个编号存在但不可见”。
    post = await db.get(MealPost, post_id)
    if post is None or post.status != "published":
        raise AppError("POST_NOT_FOUND", "这条饭帖暂时无法查看", status_code=404)
    return ok(await load_detail(db, post, viewer))


@router.post("")
async def create_post_route(
    body: CreatePostRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=64),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """直接发布（不经过草稿）。

    幂等键用于防止用户连点或网络重试造成重复发布：
    同一个用户用同一个键重复提交时，直接返回第一次的结果。
    """
    existing = await db.scalar(
        select(MealPost).where(
            MealPost.author_id == user.id,
            MealPost.client_request_id == idempotency_key,
            # 草稿不占用幂等键；已删除的内容也不能被当成成功结果返回。
            MealPost.status.notin_(["draft", "deleted"]),
        )
    )
    if existing:
        return ok(_publish_result(existing), "已提交过相同内容")

    post = await create_post(
        db, user, body, client_request_id=idempotency_key
    )
    return ok(_publish_result(post), "已发布" if post.status == "published" else "已提交审核")


@router.post("/drafts")
async def create_draft_route(
    body: DraftPostRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """保存草稿。

    草稿不要求幂等键：它本身就是一条可编辑的数据，
    重复保存只会产生多条草稿，不会像重复发布那样影响公开内容。
    如果客户端确实重复提交，可以在“我的草稿”里看到并删除多余的一条。
    """
    post = await create_draft(db, user, body)
    return ok(_draft_result(post), "草稿已保存")


@router.put("/{post_id}/draft")
async def update_draft_route(
    post_id: str,
    body: DraftPostRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    post = await update_draft(db, user, post_id, body)
    return ok(_draft_result(post), "草稿已更新")


@router.post("/{post_id}/publish")
async def publish_draft_route(
    post_id: str,
    body: CreatePostRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """把草稿补全后正式发布。

    这里不做幂等键判断：草稿发布成功后状态就变成 published，
    重复请求会在服务层收到 POST_NOT_DRAFT，不会产生第二条内容。
    """
    post = await publish_draft(db, user, post_id, body)
    return ok(_publish_result(post), "已发布" if post.status == "published" else "已提交审核")


@router.delete("/{post_id}")
async def delete_post_route(
    post_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    post = await delete_post(db, user, post_id)
    return ok(
        {
            "postId": post.id,
            "status": post.status,
            "deletedAt": iso(post.deleted_at),
        },
        "已删除",
    )


def _publish_result(post: MealPost) -> dict:
    return {
        "postId": post.id,
        "status": post.status,
        "publishedAt": iso(post.published_at),
        "reviewRequired": post.status == "pending_review",
    }


def _draft_result(post: MealPost) -> dict:
    return {
        "postId": post.id,
        "status": post.status,
        "updatedAt": iso(post.updated_at),
    }
