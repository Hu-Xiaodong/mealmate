from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import AdminPrincipal, client_ip, require_permission
from app.core.responses import ok
from app.db.session import get_db
from app.schemas import ReasonRequest
from app.services.review_service import (
    approve_post,
    get_admin_post,
    list_admin_posts,
    reject_post,
    unpublish_post,
)

router = APIRouter(prefix="/admin/posts", tags=["admin-posts"])


@router.get("")
async def list_posts(
    status_filter: str | None = Query(default=None, alias="status"),
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    principal: AdminPrincipal = Depends(require_permission("post.review")),
    db: AsyncSession = Depends(get_db),
):
    """饭帖列表，可按状态筛选。默认按提交时间倒序。"""
    return ok(
        await list_admin_posts(
            db, status=status_filter, cursor=cursor, limit=limit
        )
    )


@router.get("/{post_id}")
async def post_detail(
    post_id: str,
    principal: AdminPrincipal = Depends(require_permission("post.review")),
    db: AsyncSession = Depends(get_db),
):
    """饭帖详情，包含图片、作者、来源、定位与审核记录。"""
    return ok(await get_admin_post(db, post_id))


@router.post("/{post_id}/approve")
async def approve(
    post_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("post.review")),
    db: AsyncSession = Depends(get_db),
):
    """审核通过。重复调用返回当前状态，不重复写入。"""
    data = await approve_post(
        db, principal.admin, post_id, client_ip(request)
    )
    return ok(data, "已通过审核" if data["changed"] else "该饭帖已是公开状态")


@router.post("/{post_id}/reject")
async def reject(
    post_id: str,
    body: ReasonRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("post.review")),
    db: AsyncSession = Depends(get_db),
):
    """拒绝审核，必须填写原因。"""
    data = await reject_post(
        db, principal.admin, post_id, body.reason, client_ip(request)
    )
    return ok(data, "已拒绝" if data["changed"] else "该饭帖已被拒绝")


@router.post("/{post_id}/unpublish")
async def unpublish(
    post_id: str,
    body: ReasonRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("post.unpublish")),
    db: AsyncSession = Depends(get_db),
):
    """下架已公开饭帖，必须填写原因。"""
    data = await unpublish_post(
        db, principal.admin, post_id, body.reason, client_ip(request)
    )
    return ok(data, "已下架" if data["changed"] else "该饭帖已下架")
