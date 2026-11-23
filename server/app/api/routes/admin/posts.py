from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_deps import AdminPrincipal, client_ip, require_permission
from app.core.errors import AppError
from app.core.responses import ok
from app.db.session import get_db
from app.schemas import BatchDeleteRequest, BatchReviewRequest, ReasonRequest
from app.services.review_service import (
    approve_post,
    delete_post,
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


@router.post("/batch-review")
async def batch_review(
    body: BatchReviewRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("post.review")),
    db: AsyncSession = Depends(get_db),
):
    """批量通过或拒绝饭帖。

    每条独立处理、独立提交：一条状态不允许不会影响其他条目。
    返回逐条结果，前端可以准确展示“成功几条、失败几条、失败原因是什么”。
    """
    results = []
    succeeded = 0
    ip = client_ip(request)
    for post_id in body.post_ids:
        try:
            if body.action == "approve":
                data = await approve_post(db, principal.admin, post_id, ip)
            else:
                data = await reject_post(
                    db, principal.admin, post_id, body.reason or "", ip
                )
            succeeded += 1
            results.append(
                {
                    "postId": post_id,
                    "ok": True,
                    "status": data.get("status"),
                    "changed": data.get("changed", False),
                }
            )
        except AppError as exc:
            results.append(
                {
                    "postId": post_id,
                    "ok": False,
                    "errorCode": exc.code,
                    "message": exc.message,
                }
            )
    failed = len(results) - succeeded
    return ok(
        {
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
        },
        f"已处理 {len(results)} 条，成功 {succeeded} 条，失败 {failed} 条",
    )


@router.post("/batch-delete")
async def batch_delete(
    body: BatchDeleteRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission("post.delete")),
    db: AsyncSession = Depends(get_db),
):
    """批量删除饭帖（软删除）。

    删除权限与审核、下架分开：只有拥有 post.delete 的管理员才能调用。
    每条独立处理、独立提交，一条失败不会回滚其他条目；
    返回逐条结果，前端可以准确提示成功多少条、失败原因是什么。
    """
    results = []
    succeeded = 0
    ip = client_ip(request)
    for post_id in body.post_ids:
        try:
            data = await delete_post(
                db, principal.admin, post_id, body.reason, ip
            )
            succeeded += 1
            results.append(
                {
                    "postId": post_id,
                    "ok": True,
                    "status": data.get("status"),
                    "changed": data.get("changed", False),
                }
            )
        except AppError as exc:
            results.append(
                {
                    "postId": post_id,
                    "ok": False,
                    "errorCode": exc.code,
                    "message": exc.message,
                }
            )
    failed = len(results) - succeeded
    return ok(
        {
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
        },
        f"已处理 {len(results)} 条，成功 {succeeded} 条，失败 {failed} 条",
    )


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
