"""管理后台扩展能力与埋点、加密令牌的接口测试。

覆盖：
1. 用户与管理员令牌都是后端加密后的密文，篡改后立即失效；
2. 埋点批量上报、幂等去重、登录账号回填；
3. 饭帖批量审核；
4. 用户详情查看发布（不含草稿）；
5. 后台菜谱增改查与下架；
6. 口味标签字典维护；
7. 管理员与角色管理、权限即时生效；
8. 数据看板聚合。
"""

import pytest
from sqlalchemy import select

from app.core.security import read_session_token
from app.db.models import AnalyticsEvent, MealPost, Session
from app.main import app
from tests.conftest import API, auth_headers, data_of, login

ADMIN_PASSWORD = "Admin@123456"


async def login_as_admin(client, username: str = "admin", password: str = ADMIN_PASSWORD) -> str:
    response = await client.post(
        f"{API}/admin/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return data_of(response)["token"]


async def add_pending_posts() -> None:
    async with app.state.test_session_factory() as db:
        db.add_all(
            [
                MealPost(
                    id="p_batch_1",
                    author_id="u_adao",
                    title="批量通过一",
                    review="批量审核测试内容一，图片和文字都完整。",
                    source="self",
                    image_asset_ids=["m_seed_1"],
                    status="pending_review",
                ),
                MealPost(
                    id="p_batch_2",
                    author_id="u_adao",
                    title="批量通过二",
                    review="批量审核测试内容二，图片和文字都完整。",
                    source="self",
                    image_asset_ids=["m_seed_2"],
                    status="pending_review",
                ),
                MealPost(
                    id="p_draft_1",
                    author_id="u_adao",
                    title="用户草稿",
                    review="草稿不应出现在后台查看发布里。",
                    source="self",
                    image_asset_ids=["m_seed_3"],
                    status="draft",
                ),
            ]
        )
        await db.commit()


@pytest.mark.asyncio
async def test_user_and_admin_tokens_are_encrypted(client):
    user = await login(client, "13800000007")
    token = user["token"]
    parsed = read_session_token(token)
    assert parsed is not None
    session_id, payload = parsed
    assert token != payload

    async with app.state.test_session_factory() as db:
        session = await db.get(Session, session_id)
        assert session is not None
        assert session.account_id == user["accountId"]
        # 数据库只存摘要，不存令牌或明文载荷。
        assert session.token_digest not in {token, payload}

    # 改动一个字符后 MAC 校验失败，按未登录处理。
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    response = await client.get(f"{API}/auth/me", headers=auth_headers(tampered))
    assert response.status_code == 401

    admin_token = await login_as_admin(client)
    assert admin_token.startswith("adm_")
    admin_parsed = read_session_token(admin_token, prefix="adm_")
    assert admin_parsed is not None
    assert read_session_token(admin_token) is None  # 缺少管理员前缀不能当普通令牌使用


@pytest.mark.asyncio
async def test_analytics_batch_dedupe_and_account(client):
    events = [
        {
            "eventId": "evt_test_0001",
            "eventName": "page_view",
            "pageName": "home",
            "platform": "android",
            "appVersion": "1.2.0",
            "sessionRef": "sess_test",
            "properties": {"source": "cold_start"},
        },
        {
            "eventId": "evt_test_0002",
            "eventName": "meal_impression",
            "pageName": "home",
            "properties": {"postId": "p_1001", "position": 1},
        },
    ]
    first = await client.post(f"{API}/analytics/events", json={"events": events})
    assert first.status_code == 200, first.text
    assert data_of(first) == {"accepted": 2, "duplicated": 0, "rejected": 0}

    # 同一批重试：按 eventId 去重，不重复计数。
    again = data_of(
        await client.post(f"{API}/analytics/events", json={"events": events})
    )
    assert again == {"accepted": 0, "duplicated": 2, "rejected": 0}

    # 登录上报时由后端回填账号，事件体无法伪造账号。
    user = await login(client, "13800000006")
    logged = await client.post(
        f"{API}/analytics/events",
        json={
            "events": [
                {
                    "eventId": "evt_test_0003",
                    "eventName": "login_result",
                    "properties": {"resultCode": "success"},
                }
            ]
        },
        headers=auth_headers(user["token"]),
    )
    assert data_of(logged)["accepted"] == 1

    # 未定义事件被拒绝，不污染看板。
    unknown = data_of(
        await client.post(
            f"{API}/analytics/events",
            json={
                "events": [
                    {
                        "eventId": "evt_test_0004",
                        "eventName": "made_up_event",
                        "properties": {},
                    }
                ]
            },
        )
    )
    assert unknown["rejected"] == 1

    async with app.state.test_session_factory() as db:
        rows = (
            await db.scalars(select(AnalyticsEvent).where(AnalyticsEvent.event_id.like("evt_test_%")))
        ).all()
        by_id = {row.event_id: row for row in rows}
        assert len(by_id) == 3
        assert by_id["evt_test_0003"].account_id == user["accountId"]


@pytest.mark.asyncio
async def test_batch_review_and_user_posts(client):
    await add_pending_posts()
    headers = auth_headers(await login_as_admin(client))

    result = data_of(
        await client.post(
            f"{API}/admin/posts/batch-review",
            json={"postIds": ["p_batch_1", "p_batch_2"], "action": "approve"},
            headers=headers,
        )
    )
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert all(item["status"] == "published" for item in result["results"])

    # 混合批次：已通过的再次通过是幂等成功，不存在的帖子返回失败。
    mixed = data_of(
        await client.post(
            f"{API}/admin/posts/batch-review",
            json={"postIds": ["p_batch_1", "p_missing"], "action": "approve"},
            headers=headers,
        )
    )
    assert mixed["succeeded"] == 1
    assert mixed["failed"] == 1
    assert mixed["results"][1]["errorCode"] == "POST_NOT_FOUND"

    # 用户详情“查看发布”：包含公开内容，不包含草稿。
    posts = data_of(
        await client.get(f"{API}/admin/users/u_adao/posts", headers=headers)
    )
    ids = {item["id"] for item in posts["items"]}
    assert {"p_1001", "p_1004", "p_1007", "p_batch_1", "p_batch_2"}.issubset(ids)
    assert "p_draft_1" not in ids


@pytest.mark.asyncio
async def test_admin_recipe_crud(client):
    headers = auth_headers(await login_as_admin(client))

    created = data_of(
        await client.post(
            f"{API}/admin/recipes",
            json={
                "title": "测试青椒炒蛋",
                "coverUrl": "seed/food_3.jpg",
                "totalMinutes": 12,
                "toolCodes": ["wok"],
                "categoryCodes": ["quick", "few"],
                "servings": 1,
                "ingredients": [
                    {"name": "鸡蛋", "amount": "2 个"},
                    {"name": "青椒", "amount": "1 个"},
                ],
                "steps": ["鸡蛋打散", "青椒切丝", "大火快炒"],
                "preconditions": "需要炒锅",
                "validationStatus": "tested",
                "status": "published",
            },
            headers=headers,
        )
    )
    assert created["title"] == "测试青椒炒蛋"
    assert created["mainIngredients"] == ["鸡蛋", "青椒"]
    recipe_id = created["id"]

    listing = data_of(
        await client.get(f"{API}/admin/recipes?keyword=测试青椒", headers=headers)
    )
    assert recipe_id in [item["id"] for item in listing["items"]]

    updated = data_of(
        await client.put(
            f"{API}/admin/recipes/{recipe_id}",
            json={
                "title": "测试青椒炒蛋（改良）",
                "coverUrl": "seed/food_3.jpg",
                "totalMinutes": 10,
                "toolCodes": ["wok"],
                "categoryCodes": ["quick"],
                "servings": 2,
                "ingredients": [{"name": "鸡蛋", "amount": "3 个"}],
                "steps": ["鸡蛋打散", "下锅炒熟"],
                "status": "published",
            },
            headers=headers,
        )
    )
    assert updated["title"] == "测试青椒炒蛋（改良）"
    assert updated["servings"] == 2
    assert updated["categories"] == ["quick"]

    archived = data_of(
        await client.post(f"{API}/admin/recipes/{recipe_id}/archive", headers=headers)
    )
    assert archived["status"] == "archived"
    assert archived["changed"] is True

    # 下架后普通用户菜谱列表不可见。
    public = data_of(await client.get(f"{API}/recipes"))
    assert recipe_id not in [item["id"] for item in public["items"]]


@pytest.mark.asyncio
async def test_taste_tag_management(client):
    headers = auth_headers(await login_as_admin(client))

    created = data_of(
        await client.post(
            f"{API}/admin/taste-tags",
            json={"name": "测试微辣", "sortOrder": 50, "enabled": True},
            headers=headers,
        )
    )
    assert created["name"] == "测试微辣"
    assert created["usageCount"] == 0

    updated = data_of(
        await client.put(
            f"{API}/admin/taste-tags/测试微辣",
            json={"enabled": False, "sortOrder": 60},
            headers=headers,
        )
    )
    assert updated["enabled"] is False
    assert updated["sortOrder"] == 60

    # 停用后普通用户端字典不再返回。
    public = data_of(await client.get(f"{API}/taste-tags"))
    assert "测试微辣" not in [item["name"] for item in public["items"]]

    removed = data_of(
        await client.delete(f"{API}/admin/taste-tags/测试微辣", headers=headers)
    )
    assert removed["deleted"] is True

    # 已被饭帖使用的标签不能删除，只能停用。
    in_use = await client.delete(f"{API}/admin/taste-tags/清淡", headers=headers)
    assert in_use.status_code == 409
    assert in_use.json()["code"] == "TASTE_TAG_IN_USE"


@pytest.mark.asyncio
async def test_admin_and_role_management(client):
    headers = auth_headers(await login_as_admin(client))

    role = data_of(
        await client.post(
            f"{API}/admin/roles",
            json={
                "code": "dashboard_only",
                "name": "看板只读",
                "permissions": ["dashboard.read"],
            },
            headers=headers,
        )
    )
    role_id = role["id"]

    created_admin = data_of(
        await client.post(
            f"{API}/admin/admins",
            json={
                "username": "dash_user",
                "password": "Dash@123456",
                "displayName": "看板用户",
                "roleIds": [role_id],
            },
            headers=headers,
        )
    )
    assert created_admin["username"] == "dash_user"
    assert created_admin["roles"][0]["code"] == "dashboard_only"

    duplicate = await client.post(
        f"{API}/admin/admins",
        json={
            "username": "dash_user",
            "password": "Dash@123456",
            "displayName": "重复",
            "roleIds": [role_id],
        },
        headers=headers,
    )
    assert duplicate.status_code == 409

    dash_token = await login_as_admin(client, "dash_user", "Dash@123456")
    dash_headers = auth_headers(dash_token)
    assert (await client.get(f"{API}/admin/dashboard", headers=dash_headers)).status_code == 200
    # 没有 post.review，审核列表必须 403。
    assert (
        await client.get(f"{API}/admin/posts", headers=dash_headers)
    ).status_code == 403

    # 修改角色权限后立即生效，不需要重新登录。
    data_of(
        await client.put(
            f"{API}/admin/roles/{role_id}",
            json={"permissions": []},
            headers=headers,
        )
    )
    assert (
        await client.get(f"{API}/admin/dashboard", headers=dash_headers)
    ).status_code == 403

    # 当前登录管理员不能停用自己。
    me = data_of(await client.get(f"{API}/admin/auth/me", headers=headers))
    self_disable = await client.put(
        f"{API}/admin/admins/{me['admin']['id']}",
        json={"status": "disabled"},
        headers=headers,
    )
    assert self_disable.status_code == 409
    assert self_disable.json()["code"] == "ADMIN_SELF_PROTECTED"


@pytest.mark.asyncio
async def test_dashboard_summary(client):
    headers = auth_headers(await login_as_admin(client))
    data = data_of(await client.get(f"{API}/admin/dashboard?days=7", headers=headers))
    assert data["rangeDays"] == 7
    assert data["users"]["total"] >= 3
    assert data["posts"]["published"] >= 1
    assert len(data["trend"]) == 7
    assert "pending" in data["posts"]
