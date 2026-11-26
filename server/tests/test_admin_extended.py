"""管理后台扩展能力与埋点、加密令牌的接口测试。

覆盖：
1. 用户与管理员令牌都是后端加密后的密文，篡改后立即失效；
2. 埋点批量上报、幂等去重、登录账号回填；
3. 饭帖批量审核；
4. 用户详情查看发布（不含草稿）；
5. 后台菜谱增改查、下架与批量上下架/删除；
6. 口味标签字典维护；
7. 管理员与角色管理、权限即时生效；
8. 数据看板聚合；
9. 后台列表统一页码分页。
"""

import pytest
from sqlalchemy import func, select

from app.core.security import read_session_token
from app.db.models import AnalyticsEvent, MealPost, Recipe, RecipeCategory, Session
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
            await db.scalars(
                select(AnalyticsEvent).where(
                    AnalyticsEvent.event_id.like("evt_test_%")
                )
            )
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
async def test_admin_recipe_batch_operations(client):
    """批量上架、下架、删除：逐条返回结果，被饭帖引用的菜谱不能删除。"""
    headers = auth_headers(await login_as_admin(client))

    async def create(title: str, status: str) -> str:
        response = await client.post(
            f"{API}/admin/recipes",
            json={
                "title": title,
                "coverUrl": "seed/food_3.jpg",
                "totalMinutes": 10,
                "categoryCodes": ["quick"],
                "ingredients": [{"name": "鸡蛋", "amount": "2 个"}],
                "steps": ["炒熟"],
                "status": status,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        return data_of(response)["id"]

    published_id = await create("批量测试已发布", "published")
    draft_id = await create("批量测试草稿", "draft")
    spare_id = await create("批量测试待删除", "published")

    # 1. 批量下架：已发布的和草稿都会变成 archived。
    archived = data_of(
        await client.post(
            f"{API}/admin/recipes/batch-archive",
            json={"recipeIds": [published_id, draft_id]},
            headers=headers,
        )
    )
    assert archived["succeeded"] == 2
    assert archived["failed"] == 0

    # 2. 重复下架：状态没变，记为跳过而不是失败。
    archived_again = data_of(
        await client.post(
            f"{API}/admin/recipes/batch-archive",
            json={"recipeIds": [published_id, draft_id]},
            headers=headers,
        )
    )
    assert archived_again["succeeded"] == 0
    assert archived_again["skipped"] == 2

    # 3. 批量上架：下架的菜谱重新可见。
    published = data_of(
        await client.post(
            f"{API}/admin/recipes/batch-publish",
            json={"recipeIds": [published_id, draft_id]},
            headers=headers,
        )
    )
    assert published["succeeded"] == 2
    detail = data_of(await client.get(f"{API}/admin/recipes/{draft_id}", headers=headers))
    assert detail["status"] == "published"

    # 造一条引用平台菜谱的饭帖，用来验证删除保护。
    async with app.state.test_session_factory() as db:
        db.add(
            MealPost(
                id="p_batch_recipe_ref",
                author_id="u_adao",
                title="引用平台菜谱",
                review="这道菜来自平台菜谱，删除菜谱后历史饭帖会失去来源。",
                source="platform",
                image_asset_ids=["m_seed_1"],
                platform_recipe_id=published_id,
                status="published",
            )
        )
        await db.commit()

    # 4. 批量删除：被引用的跳过，其余物理删除。
    deleted = data_of(
        await client.post(
            f"{API}/admin/recipes/batch-delete",
            json={"recipeIds": [published_id, draft_id, spare_id]},
            headers=headers,
        )
    )
    assert deleted["succeeded"] == 2
    assert deleted["skipped"] == 1
    skipped = [item for item in deleted["results"] if item.get("skipped")]
    assert skipped[0]["recipeId"] == published_id

    async with app.state.test_session_factory() as db:
        # 被引用的菜谱仍然存在；其余菜谱和它们的分类关联都已删除。
        assert await db.get(Recipe, published_id) is not None
        assert await db.get(Recipe, draft_id) is None
        assert await db.get(Recipe, spare_id) is None
        category_count = await db.scalar(
            select(func.count())
            .select_from(RecipeCategory)
            .where(RecipeCategory.recipe_id.in_([draft_id, spare_id]))
        )
        assert category_count == 0

    # 5. 一条不存在的编号只影响自己，其余照常处理。
    missing = data_of(
        await client.post(
            f"{API}/admin/recipes/batch-archive",
            json={"recipeIds": ["r_not_exists"]},
            headers=headers,
        )
    )
    assert missing["failed"] == 1
    assert missing["results"][0]["errorCode"] == "RECIPE_NOT_FOUND"

    # 6. 超过 50 条时由请求模型直接拒绝，避免一次请求长时间占用连接。
    too_many = await client.post(
        f"{API}/admin/recipes/batch-delete",
        json={"recipeIds": [f"r_many_{index}" for index in range(51)]},
        headers=headers,
    )
    assert too_many.status_code == 422


@pytest.mark.asyncio
async def test_published_recipe_without_category_defaults_to_recommended(client):
    """没有分类的菜谱上架后必须出现在 App 的“推荐”列表里。

    回归背景：知识库生成的草稿分类为空，批量上架后状态确实是 published，
    但客户端列表按分类关联表筛选，导致这些菜谱在 App 里完全看不到，
    表现为“管理后台已发布、移动端没有同步”。
    """
    headers = auth_headers(await login_as_admin(client))

    # 1. 直接以已发布状态创建且不选分类：创建接口自动补“推荐”。
    created = data_of(
        await client.post(
            f"{API}/admin/recipes",
            json={
                "title": "无分类直接发布",
                "coverUrl": "seed/food_3.jpg",
                "totalMinutes": 10,
                "ingredients": [{"name": "鸡蛋", "amount": "2 个"}],
                "steps": ["炒熟"],
                "status": "published",
            },
            headers=headers,
        )
    )
    assert created["categories"] == ["recommended"]
    public = data_of(await client.get(f"{API}/recipes", params={"limit": 50}))
    assert created["id"] in [item["id"] for item in public["items"]]

    # 2. 草稿创建时分类为空，批量上架时同样要补“推荐”，并写入关联表。
    draft = data_of(
        await client.post(
            f"{API}/admin/recipes",
            json={
                "title": "无分类草稿上架",
                "coverUrl": "seed/food_3.jpg",
                "totalMinutes": 10,
                "ingredients": [{"name": "鸡蛋", "amount": "2 个"}],
                "steps": ["炒熟"],
                "status": "draft",
            },
            headers=headers,
        )
    )
    assert draft["categories"] == []
    published = data_of(
        await client.post(
            f"{API}/admin/recipes/batch-publish",
            json={"recipeIds": [draft["id"]]},
            headers=headers,
        )
    )
    assert published["succeeded"] == 1
    detail = data_of(
        await client.get(f"{API}/admin/recipes/{draft['id']}", headers=headers)
    )
    assert detail["categories"] == ["recommended"]
    public_after = data_of(await client.get(f"{API}/recipes", params={"limit": 50}))
    assert draft["id"] in [item["id"] for item in public_after["items"]]


@pytest.mark.asyncio
async def test_admin_lists_use_page_pagination(client):
    """后台列表统一返回页码分页结构：items、total、page、pageSize。"""
    headers = auth_headers(await login_as_admin(client))

    # 饭帖：每页 2 条，前后两页不能出现同一条。
    posts_page1 = data_of(
        await client.get(
            f"{API}/admin/posts", params={"page": 1, "pageSize": 2}, headers=headers
        )
    )
    posts_page2 = data_of(
        await client.get(
            f"{API}/admin/posts", params={"page": 2, "pageSize": 2}, headers=headers
        )
    )
    assert posts_page1["page"] == 1
    assert posts_page1["pageSize"] == 2
    assert posts_page1["total"] >= 4
    assert len(posts_page1["items"]) == 2
    first_ids = {item["id"] for item in posts_page1["items"]}
    second_ids = {item["id"] for item in posts_page2["items"]}
    assert first_ids.isdisjoint(second_ids)

    # 用户：返回总数，并允许切换每页条数。
    users = data_of(
        await client.get(
            f"{API}/admin/users", params={"page": 1, "pageSize": 3}, headers=headers
        )
    )
    assert users["page"] == 1
    assert users["pageSize"] == 3
    assert users["total"] >= 3
    assert len(users["items"]) == 3

    # 菜谱：第一页和第二页的编号不重复。
    recipes_page1 = data_of(
        await client.get(
            f"{API}/admin/recipes", params={"page": 1, "pageSize": 1}, headers=headers
        )
    )
    recipes_page2 = data_of(
        await client.get(
            f"{API}/admin/recipes", params={"page": 2, "pageSize": 1}, headers=headers
        )
    )
    assert recipes_page1["total"] >= 2
    assert recipes_page1["items"][0]["id"] != recipes_page2["items"][0]["id"]

    # 先做一次写操作，确保审计日志里至少有本次创建的记录。
    await client.post(
        f"{API}/admin/recipes",
        json={
            "title": "分页测试菜谱",
            "coverUrl": "seed/food_3.jpg",
            "totalMinutes": 10,
            "ingredients": [{"name": "鸡蛋", "amount": "2 个"}],
            "steps": ["炒熟"],
            "status": "draft",
        },
        headers=headers,
    )
    audit = data_of(
        await client.get(
            f"{API}/admin/audit-logs", params={"page": 1, "pageSize": 5}, headers=headers
        )
    )
    assert audit["total"] >= 1
    assert audit["page"] == 1
    assert audit["pageSize"] == 5

    # AI 调用日志：即使暂时没有记录，也要返回完整的分页结构。
    ai_logs = data_of(
        await client.get(
            f"{API}/admin/ai-call-logs", params={"page": 1, "pageSize": 5}, headers=headers
        )
    )
    assert ai_logs["page"] == 1
    assert ai_logs["pageSize"] == 5
    assert ai_logs["total"] >= 0


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
