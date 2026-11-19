from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.serializers import iso
from app.core.errors import AppError
from app.core.responses import ok
from app.core.security import new_id
from app.db.models import Favorite, Like, MealPost, Recipe, User
from app.db.session import get_db
from app.schemas import FavoriteRequest, LikeRequest
from app.utils.time import now_utc

router = APIRouter(tags=["interactions"])


async def _effective_like_count(db: AsyncSession, post_id: str) -> int:
    count = await db.scalar(
        select(func.count(Like.id)).where(
            Like.post_id == post_id,
            Like.active.is_(True),
            Like.risk_status == "valid",
        )
    )
    return int(count or 0)


@router.put("/posts/{post_id}/like")
async def set_like(
    post_id: str,
    body: LikeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    post = await db.get(MealPost, post_id)
    if post is None or post.status != "published":
        raise AppError("POST_NOT_FOUND", "这条饭帖暂时无法查看", status_code=404)

    like = await db.scalar(
        select(Like).where(Like.account_id == user.id, Like.post_id == post_id)
    )
    if like is None and body.liked:
        like = Like(id=new_id("l"), account_id=user.id, post_id=post_id, active=True)
        db.add(like)
    elif like is not None:
        like.active = body.liked
        if body.liked:
            like.risk_status = "valid"
        like.updated_at = now_utc()

    await db.commit()
    return ok(
        {
            "postId": post_id,
            "liked": body.liked,
            "likeCount": await _effective_like_count(db, post_id),
        }
    )


@router.put("/favorites")
async def set_favorite(
    body: FavoriteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.target_type == "post":
        target = await db.get(MealPost, body.target_id)
        visible = target is not None and target.status == "published"
    else:
        target = await db.get(Recipe, body.target_id)
        visible = target is not None and target.status == "published"
    if not visible:
        raise AppError("TARGET_NOT_FOUND", "目标内容暂时无法收藏", status_code=404)

    favorite = await db.scalar(
        select(Favorite).where(
            Favorite.account_id == user.id,
            Favorite.target_type == body.target_type,
            Favorite.target_id == body.target_id,
        )
    )

    saved_at = None
    if body.saved:
        if favorite is None:
            favorite = Favorite(
                id=new_id("f"),
                account_id=user.id,
                target_type=body.target_type,
                target_id=body.target_id,
                saved_at=now_utc(),
            )
            db.add(favorite)
            await db.commit()
            await db.refresh(favorite)
        saved_at = iso(favorite.saved_at)
    elif favorite is not None:
        await db.delete(favorite)
        await db.commit()

    return ok(
        {
            "targetType": body.target_type,
            "targetId": body.target_id,
            "saved": body.saved,
            "savedAt": saved_at,
        }
    )
