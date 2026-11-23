"""管理后台第一阶段的接口测试。

覆盖验收标准：
1. 超级管理员能登录并拿到权限点；
2. 待审饭帖可通过、可拒绝，拒绝必须填原因；
3. 作者能在“我的发布”看到审核状态与原因；
4. 已公开内容可下架，下架后公开列表不可见；
5. 封禁用户后其会话立即失效；
6. 审计日志记录操作人、动作、对象、原因与请求标识。
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.security import hash_password, new_id
from app.db.models import (
    AdminRole,
    AdminUser,
    AdminUserRole,
    Like,
    MealPost,
)
from app.main import app
from app.utils.time import BUSINESS_TZ
from tests.conftest import API, auth_headers, data_of, login

ADMIN_PASSWORD = "Admin@123456"


async def admin_login(client, username: str = "admin", password: str = ADMIN_PASSWORD):
    return await client.post(
        f"{API}/admin/auth/login",
        json={"username": username, "password": password},
    )


async def login_as_admin(client) -> str:
    response = await admin_login(client)
    assert response.status_code == 200, response.text
    return data_of(response)["token"]


async def create_admin(username: str, password: str, role_code: str) -> None:
    """直接写库创建指定角色的管理员，用于权限与锁定测试。"""
    async with app.state.test_session_factory() as db:
        role = await db.scalar(select(AdminRole).where(AdminRole.code == role_code))
        assert role is not None
        admin = AdminUser(
            id=new_id("adm"),
            username=username,
            password_hash=hash_password(password),
            display_name=username,
            status="active",
        )
        db.add(admin)
        await db.flush()
        db.add(
            AdminUserRole(
                id=new_id("aur"), admin_id=admin.id, role_id=role.id
            )
        )
        await db.commit()


async def create_pending_posts() -> None:
    async with app.state.test_session_factory() as db:
        db.add_all(
            [
                MealPost(
                    id="p_admin_reject",
                    author_id="u_adao",
                    title="待拒绝饭帖",
                    review="这张图片不够清晰，用于测试拒绝流程。",
                    source="self",
                    image_asset_ids=["m_seed_1"],
                    status="pending_review",
                ),
                MealPost(
                    id="p_admin_approve",
                    author_id="u_adao",
                    title="待通过饭帖",
                    review="这是一条会进入首页和热榜的测试内容。",
                    source="self",
                    image_asset_ids=["m_seed_2"],
                    status="pending_review",
                ),
            ]
        )
        await db.flush()
        # 给待通过的饭帖加一个有效赞，审核通过后应出现在热榜。
        db.add(
            Like(
                id="l_admin_test",
                account_id="u_like1",
                post_id="p_admin_approve",
                active=True,
                risk_status="valid",
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_admin_login_me_and_logout(client):
    response = await admin_login(client)
    assert response.status_code == 200, response.text
    payload = data_of(response)
    assert payload["token"].startswith("adm_")
    assert payload["tokenType"] == "Bearer"
    assert "post.review" in payload["permissions"]
    assert "audit.read" in payload["permissions"]

    headers = auth_headers(payload["token"])
    me = await client.get(f"{API}/admin/auth/me", headers=headers)
    me_data = data_of(me)
    assert me_data["admin"]["username"] == "admin"
    assert "post.review" in me_data["permissions"]

    # 注销后同一个令牌立即失效，不能继续访问后台接口。
    out = await client.post(f"{API}/admin/auth/logout", headers=headers)
    assert out.status_code == 200, out.text
    after = await client.get(f"{API}/admin/auth/me", headers=headers)
    assert after.status_code == 401
    assert after.json()["code"] == "ADMIN_SESSION_INVALID"


@pytest.mark.asyncio
async def test_admin_login_lockout(client):
    await create_admin("ops_lock", "Lock@123456", "content_operator")

    for _ in range(4):
        response = await admin_login(client, "ops_lock", "Wrong@123456")
        assert response.status_code == 401
        assert response.json()["code"] == "ADMIN_LOGIN_FAILED"

    # 第 5 次失败触发锁定，返回 423 和剩余秒数。
    fifth = await admin_login(client, "ops_lock", "Wrong@123456")
    assert fifth.status_code == 423
    assert fifth.json()["code"] == "ADMIN_LOGIN_LOCKED"
    assert fifth.json()["data"]["retryAfter"] > 0

    # 锁定期间即使密码正确也不允许登录。
    correct = await admin_login(client, "ops_lock", "Lock@123456")
    assert correct.status_code == 423


@pytest.mark.asyncio
async def test_auditor_can_only_read(client):
    await create_admin("auditor_one", "Audit@123456", "auditor")
    response = await admin_login(client, "auditor_one", "Audit@123456")
    token = data_of(response)["token"]
    headers = auth_headers(token)

    # 审计员可以看用户列表和审计日志。
    users = await client.get(f"{API}/admin/users", headers=headers)
    assert users.status_code == 200
    logs = await client.get(f"{API}/admin/audit-logs", headers=headers)
    assert logs.status_code == 200

    # 没有 post.review 权限，审核接口必须返回 403。
    denied = await client.post(
        f"{API}/admin/posts/p_admin_reject/approve", headers=headers
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "ADMIN_PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_review_flow_and_public_visibility(client):
    await create_pending_posts()
    token = await login_as_admin(client)
    headers = auth_headers(token)

    # 预热热榜缓存：此时待审内容还不应该出现。
    rank_before = data_of(await client.get(f"{API}/rank/today"))
    assert "p_admin_approve" not in [item["id"] for item in rank_before["items"]]

    pending = data_of(
        await client.get(f"{API}/admin/posts?status=pending_review", headers=headers)
    )
    pending_ids = [item["id"] for item in pending["items"]]
    assert "p_admin_reject" in pending_ids
    assert "p_admin_approve" in pending_ids

    detail = data_of(
        await client.get(f"{API}/admin/posts/p_admin_reject", headers=headers)
    )
    assert detail["title"] == "待拒绝饭帖"
    assert detail["author"]["nickname"] == "阿豆"

    # 原因不足 2 个字时请求校验失败。
    blank = await client.post(
        f"{API}/admin/posts/p_admin_reject/reject",
        json={"reason": " "},
        headers=headers,
    )
    assert blank.status_code == 422

    rejected = data_of(
        await client.post(
            f"{API}/admin/posts/p_admin_reject/reject",
            json={"reason": "图片不清晰"},
            headers=headers,
        )
    )
    assert rejected["status"] == "rejected"
    assert rejected["changed"] is True

    # 已拒绝的内容不能再通过，状态机拒绝非法流转。
    invalid = await client.post(
        f"{API}/admin/posts/p_admin_reject/approve", headers=headers
    )
    assert invalid.status_code == 409
    assert invalid.json()["code"] == "POST_STATUS_TRANSITION_INVALID"

    approved = data_of(
        await client.post(
            f"{API}/admin/posts/p_admin_approve/approve", headers=headers
        )
    )
    assert approved["status"] == "published"
    assert approved["publishedAt"] is not None

    feed = data_of(await client.get(f"{API}/feed"))
    assert "p_admin_approve" in [item["id"] for item in feed["items"]]

    rank_after = data_of(await client.get(f"{API}/rank/today"))
    assert "p_admin_approve" in [item["id"] for item in rank_after["items"]]

    # 作者视角：被拒绝的帖子能看到原因。
    author = await login(client, "13900000001")
    mine = data_of(
        await client.get(
            f"{API}/me/posts", headers=auth_headers(author["token"])
        )
    )
    mine_rejected = next(
        item for item in mine["items"] if item["id"] == "p_admin_reject"
    )
    assert mine_rejected["status"] == "rejected"
    assert mine_rejected["reviewReason"] == "图片不清晰"

    # 下架后首页与热榜立即不可见；重复下架是幂等的。
    unpublished = data_of(
        await client.post(
            f"{API}/admin/posts/p_admin_approve/unpublish",
            json={"reason": "内容与事实不符"},
            headers=headers,
        )
    )
    assert unpublished["status"] == "unpublished"
    feed_after = data_of(await client.get(f"{API}/feed"))
    assert "p_admin_approve" not in [item["id"] for item in feed_after["items"]]
    rank_final = data_of(await client.get(f"{API}/rank/today"))
    assert "p_admin_approve" not in [item["id"] for item in rank_final["items"]]

    again = data_of(
        await client.post(
            f"{API}/admin/posts/p_admin_approve/unpublish",
            json={"reason": "重复操作"},
            headers=headers,
        )
    )
    assert again["changed"] is False

    logs = data_of(
        await client.get(
            f"{API}/admin/audit-logs?targetId=p_admin_approve", headers=headers
        )
    )
    actions = {item["action"] for item in logs["items"]}
    assert {"post.approve", "post.unpublish"}.issubset(actions)
    assert all(item["actorName"] for item in logs["items"])
    assert all(item["requestId"] for item in logs["items"])


@pytest.mark.asyncio
async def test_ban_user_revokes_sessions_and_writes_audit(client):
    normal = await login(client, "13800000009")
    user_headers = auth_headers(normal["token"])
    assert (await client.get(f"{API}/auth/me", headers=user_headers)).status_code == 200

    admin_token = await login_as_admin(client)
    headers = auth_headers(admin_token)

    searched = data_of(
        await client.get(f"{API}/admin/users?keyword=0009", headers=headers)
    )
    target = next(
        item for item in searched["items"] if item["phoneMasked"].endswith("0009")
    )
    assert target["status"] == "active"

    detail = data_of(
        await client.get(f"{API}/admin/users/{target['id']}", headers=headers)
    )
    assert detail["postCount"] == 0
    assert detail["likeCount"] == 0
    assert detail["favoriteCount"] == 0

    banned = data_of(
        await client.post(
            f"{API}/admin/users/{target['id']}/ban",
            json={"reason": "多次发布违规内容"},
            headers=headers,
        )
    )
    assert banned["status"] == "disabled"
    assert banned["changed"] is True

    # 封禁必须撤销旧会话，否则用户还能用旧令牌继续操作。
    revoked = await client.get(f"{API}/auth/me", headers=user_headers)
    assert revoked.status_code == 401

    logs = data_of(
        await client.get(f"{API}/admin/audit-logs?action=user.ban", headers=headers)
    )
    assert any(
        item["targetId"] == target["id"] and item["reason"] == "多次发布违规内容"
        for item in logs["items"]
    )

    unbanned = data_of(
        await client.post(
            f"{API}/admin/users/{target['id']}/unban", headers=headers
        )
    )
    assert unbanned["status"] == "active"
    assert unbanned["changed"] is True

    # 审计日志没有修改和删除接口。
    delete = await client.delete(f"{API}/admin/audit-logs", headers=headers)
    assert delete.status_code == 405


async def test_batch_delete_published_posts_is_soft_delete(client):
    """批量删除已上架饭帖：后台与公开列表都不可见，但记录和审计保留。"""
    headers = auth_headers(await login_as_admin(client))

    result = data_of(
        await client.post(
            f"{API}/admin/posts/batch-delete",
            json={
                "postIds": ["p_1001", "p_missing"],
                "reason": "内容重复，测试批量删除",
            },
            headers=headers,
        )
    )
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["results"][0]["status"] == "deleted"
    assert result["results"][0]["changed"] is True
    assert result["results"][1]["errorCode"] == "POST_NOT_FOUND"

    # 公开首页不再展示。
    feed_ids = {item["id"] for item in data_of(await client.get(f"{API}/feed"))["items"]}
    assert "p_1001" not in feed_ids

    # 后台默认列表也不再展示；显式筛 deleted 仍可追溯。
    admin_ids = {
        item["id"]
        for item in data_of(
            await client.get(f"{API}/admin/posts", headers=headers)
        )["items"]
    }
    assert "p_1001" not in admin_ids
    deleted_ids = {
        item["id"]
        for item in data_of(
            await client.get(
                f"{API}/admin/posts?status=deleted", headers=headers
            )
        )["items"]
    }
    assert "p_1001" in deleted_ids

    # 删除原因写入审计日志，动作是 post.delete。
    logs = data_of(
        await client.get(
            f"{API}/admin/audit-logs?targetId=p_1001&action=post.delete",
            headers=headers,
        )
    )
    assert logs["items"]
    assert logs["items"][0]["reason"] == "内容重复，测试批量删除"

    # 重复删除是幂等的，不会重复写状态。
    again = data_of(
        await client.post(
            f"{API}/admin/posts/batch-delete",
            json={"postIds": ["p_1001"], "reason": "重复删除"},
            headers=headers,
        )
    )
    assert again["succeeded"] == 1
    assert again["results"][0]["changed"] is False


async def test_batch_delete_requires_post_delete_permission(client):
    """内容运营只有审核与下架权限，不能调用删除接口。"""
    await create_admin("content02", ADMIN_PASSWORD, "content_operator")
    login_response = await client.post(
        f"{API}/admin/auth/login",
        json={"username": "content02", "password": ADMIN_PASSWORD},
    )
    headers = auth_headers(data_of(login_response)["token"])
    denied = await client.post(
        f"{API}/admin/posts/batch-delete",
        json={"postIds": ["p_1002"], "reason": "越权删除测试"},
        headers=headers,
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "ADMIN_PERMISSION_DENIED"


async def test_audit_filter_interprets_naive_time_as_business_timezone(client):
    """前端不带时区的时间按北京时间解释，不能整体偏移 8 小时。"""
    await create_pending_posts()
    headers = auth_headers(await login_as_admin(client))

    approved = await client.post(
        f"{API}/admin/posts/p_admin_approve/approve", headers=headers
    )
    assert approved.status_code == 200, approved.text

    # 用“现在的北京时间”构造一个前后 10 分钟的无时区窗口。
    now_local = datetime.now(UTC).astimezone(BUSINESS_TZ)
    start = (now_local - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")
    end = (now_local + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")
    logs = data_of(
        await client.get(
            f"{API}/admin/audit-logs?targetId=p_admin_approve&startAt={start}&endAt={end}",
            headers=headers,
        )
    )
    assert any(item["action"] == "post.approve" for item in logs["items"])
