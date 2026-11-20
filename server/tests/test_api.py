"""核心 API 契约测试：覆盖 PRD 的浏览、登录、互动、发布、AI 配额主流程。"""

import io

from conftest import API, auth_headers, data_of, login
from PIL import Image

from app.services.map_service import parse_place_items
from app.utils.time import business_date


async def test_healthz_and_request_id(client):
    resp = await client.get("/healthz", headers={"X-Request-Id": "trace-123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["requestId"] == "trace-123"
    assert resp.headers["x-request-id"] == "trace-123"


async def test_feed_returns_today_posts_with_cursor(client):
    first = await client.get(f"{API}/feed", params={"limit": 3})
    assert first.status_code == 200
    page1 = data_of(first)
    assert page1["filter"] == "all"
    assert page1["businessDate"] == business_date().isoformat()
    assert [item["id"] for item in page1["items"]] == ["p_1009", "p_1008", "p_1007"]
    assert page1["hasMore"] is True
    assert page1["nextCursor"]

    second = await client.get(
        f"{API}/feed", params={"limit": 3, "cursor": page1["nextCursor"]}
    )
    page2 = data_of(second)
    assert [item["id"] for item in page2["items"]] == ["p_1006", "p_1005", "p_1004"]
    assert page2["hasMore"] is True


async def test_feed_rejects_broken_cursor(client):
    resp = await client.get(f"{API}/feed", params={"cursor": "not-a-cursor"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "CURSOR_INVALID"


async def test_near_feed_requires_location(client):
    resp = await client.get(f"{API}/feed", params={"filter": "near"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "LOCATION_REQUIRED"

    near = data_of(
        await client.get(
            f"{API}/feed", params={"filter": "near", "lat": 31.23, "lng": 121.47}
        )
    )
    assert [item["id"] for item in near["items"]] == [
        "p_1005",
        "p_1004",
        "p_1003",
        "p_1002",
        "p_1001",
    ]
    assert all(item["distanceMeters"] == 0 for item in near["items"])

    far = await client.get(
        f"{API}/feed", params={"filter": "near", "lat": 0.0, "lng": 0.0}
    )
    assert data_of(far)["items"] == []


async def test_rank_today_sorted_by_effective_likes(client):
    data = data_of(await client.get(f"{API}/rank/today"))
    assert data["statDate"] == business_date().isoformat()
    items = data["items"]
    assert len(items) == 8
    assert items[0]["id"] == "p_1001"
    assert items[0]["rank"] == 1
    assert items[0]["effectiveLikeCount"] == 11
    counts = [item["effectiveLikeCount"] for item in items]
    assert counts == sorted(counts, reverse=True)


async def test_recipes_category_and_detail(client):
    listing = data_of(await client.get(f"{API}/recipes", params={"category": "quick"}))
    assert listing["items"]
    assert all("quick" in item["categories"] for item in listing["items"])

    detail = data_of(await client.get(f"{API}/recipes/r_101"))
    assert detail["title"] == "番茄鸡蛋盖饭"
    assert detail["steps"]
    assert detail["savedByMe"] is False

    missing = await client.get(f"{API}/recipes/r_999")
    assert missing.status_code == 404
    assert missing.json()["code"] == "RECIPE_NOT_FOUND"


async def test_post_detail_prefers_author_recipe(client):
    with_author = data_of(await client.get(f"{API}/posts/p_1001"))
    assert with_author["recipeOrigin"] == "author"
    assert with_author["authorRecipe"]["ingredients"]
    assert with_author["recipe"] is None

    with_platform = data_of(await client.get(f"{API}/posts/p_1002"))
    assert with_platform["recipeOrigin"] == "platform_reference"
    assert with_platform["recipe"]["id"] == "r_101"


async def test_auth_flow_rate_limit_and_revoke(client):
    phone = "13800000001"
    first = await client.post(f"{API}/auth/sms-codes", json={"phone": phone})
    assert first.status_code == 200
    challenge = data_of(first)
    assert challenge["devCode"] == "123456"

    again = await client.post(f"{API}/auth/sms-codes", json={"phone": phone})
    assert again.status_code == 429
    assert again.json()["code"] == "SMS_RATE_LIMITED"
    assert again.json()["data"]["retryAfter"] > 0

    wrong = await client.post(
        f"{API}/auth/login",
        json={
            "challengeId": challenge["challengeId"],
            "code": "000000",
            "agreementAccepted": True,
        },
    )
    assert wrong.status_code == 400
    assert wrong.json()["code"] == "CODE_INVALID"
    assert wrong.json()["data"]["remainingAttempts"] == 4

    no_agreement = await client.post(
        f"{API}/auth/login",
        json={
            "challengeId": challenge["challengeId"],
            "code": "123456",
            "agreementAccepted": False,
        },
    )
    assert no_agreement.status_code == 400
    assert no_agreement.json()["code"] == "AGREEMENT_REQUIRED"

    logged = data_of(
        await client.post(
            f"{API}/auth/login",
            json={
                "challengeId": challenge["challengeId"],
                "code": "123456",
                "agreementAccepted": True,
            },
        )
    )
    assert logged["tokenType"] == "Bearer"
    assert logged["profile"]["nickname"] == "饭友0001"
    assert logged["profile"]["phoneMasked"] == "138****0001"

    headers = auth_headers(logged["token"])
    me = data_of(await client.get(f"{API}/auth/me", headers=headers))
    assert me["accountId"] == logged["accountId"]

    await client.post(f"{API}/auth/logout", headers=headers)
    revoked = await client.get(f"{API}/auth/me", headers=headers)
    assert revoked.status_code == 401
    assert revoked.json()["code"] == "SESSION_EXPIRED"


async def test_like_requires_login_and_updates_count(client):
    anonymous = await client.put(f"{API}/posts/p_1001/like", json={"liked": True})
    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "UNAUTHENTICATED"

    session = await login(client)

    liked = data_of(
        await client.put(
            f"{API}/posts/p_1001/like",
            json={"liked": True},
            headers=auth_headers(session["token"]),
        )
    )
    assert liked["liked"] is True
    assert liked["likeCount"] == 12

    detail = data_of(
        await client.get(f"{API}/posts/p_1001", headers=auth_headers(session["token"]))
    )
    assert detail["likedByMe"] is True

    unliked = data_of(
        await client.put(
            f"{API}/posts/p_1001/like",
            json={"liked": False},
            headers=auth_headers(session["token"]),
        )
    )
    assert unliked["liked"] is False
    assert unliked["likeCount"] == 11


async def test_favorites_and_me_lists(client):
    session = await login(client)
    headers = auth_headers(session["token"])

    for target_type, target_id in (("post", "p_1003"), ("recipe", "r_101")):
        saved = data_of(
            await client.put(
                f"{API}/favorites",
                json={"targetType": target_type, "targetId": target_id, "saved": True},
                headers=headers,
            )
        )
        assert saved["saved"] is True
        assert saved["savedAt"]

    favorites = data_of(await client.get(f"{API}/me/favorites", headers=headers))
    assert [item["targetType"] for item in favorites["items"]] == ["recipe", "post"]
    assert all(item["available"] is True for item in favorites["items"])

    removed = data_of(
        await client.put(
            f"{API}/favorites",
            json={"targetType": "post", "targetId": "p_1003", "saved": False},
            headers=headers,
        )
    )
    assert removed["saved"] is False
    after = data_of(await client.get(f"{API}/me/favorites", headers=headers))
    assert len(after["items"]) == 1


async def test_create_post_with_media_and_idempotency(client):
    session = await login(client)
    headers = auth_headers(session["token"])

    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), (204, 70, 44)).save(buffer, format="PNG")
    upload = await client.post(
        f"{API}/media",
        files={"file": ("meal.png", buffer.getvalue(), "image/png")},
        headers=headers,
    )
    media = data_of(upload)
    assert media["width"] == 800
    assert media["url"].startswith("/media/uploads/")

    body = {
        "title": "测试盖饭",
        "review": "自己做的，十五分钟上桌。",
        "source": "self",
        "imageAssetIds": [media["assetId"]],
    }
    post_headers = {**headers, "Idempotency-Key": "publish-key-0001"}
    created = await client.post(f"{API}/posts", json=body, headers=post_headers)
    assert created.status_code == 200
    result = data_of(created)
    assert result["status"] == "published"
    assert result["publishedAt"]
    assert result["reviewRequired"] is False

    replay = data_of(await client.post(f"{API}/posts", json=body, headers=post_headers))
    assert replay["postId"] == result["postId"]

    mine = data_of(await client.get(f"{API}/me/posts", headers=headers))
    assert mine["items"][0]["id"] == result["postId"]

    duplicated = await client.post(
        f"{API}/posts",
        json={**body, "imageAssetIds": [media["assetId"], media["assetId"]]},
        headers={**headers, "Idempotency-Key": "publish-key-0002"},
    )
    assert duplicated.status_code == 400
    assert duplicated.json()["code"] == "IMAGE_DUPLICATED"


async def test_create_post_requires_idempotency_key(client):
    session = await login(client)
    resp = await client.post(
        f"{API}/posts",
        json={
            "title": "缺少幂等键",
            "review": "会被参数校验拦截。",
            "source": "self",
            "imageAssetIds": ["m_seed_1"],
        },
        headers=auth_headers(session["token"]),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_FAILED"


async def test_takeaway_requires_store(client):
    session = await login(client)
    resp = await client.post(
        f"{API}/posts",
        json={
            "title": "外卖饭帖",
            "review": "没填店名。",
            "source": "takeaway",
            "imageAssetIds": ["m_seed_1"],
        },
        headers={**auth_headers(session["token"]), "Idempotency-Key": "publish-key-0003"},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_FAILED"


async def test_ai_guest_quota_and_recommendations(client):
    headers = {"X-Device-Id": "guest-test-device"}
    body = {"message": "下班只有十五分钟，能做什么？", "constraints": {"maxMinutes": 20}}

    for expected_used in range(1, 6):
        resp = await client.post(f"{API}/ai/chat", json=body, headers=headers)
        assert resp.status_code == 200
        data = data_of(resp)
        assert data["origin"] == "ai_reference"
        assert data["quota"] == {
            "limit": 5,
            "used": expected_used,
            "remaining": 5 - expected_used,
        }
        assert data["recommendations"]
        assert all(item["targetType"] == "recipe" for item in data["recommendations"])

    exceeded = await client.post(f"{API}/ai/chat", json=body, headers=headers)
    assert exceeded.status_code == 429
    assert exceeded.json()["code"] == "AI_QUOTA_EXCEEDED"
    assert exceeded.json()["data"] == {"limit": 5, "used": 5}


async def test_media_rejects_non_image(client):
    session = await login(client)
    resp = await client.post(
        f"{API}/media",
        files={"file": ("note.txt", b"not an image", "text/plain")},
        headers=auth_headers(session["token"]),
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "FILE_INVALID"


async def _upload_png(client, headers) -> dict:
    """上传一张最小可用的 PNG，返回媒体信息。

    多个用例都需要“自己的图片”，抽成小函数避免重复代码。
    """
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), (204, 70, 44)).save(buffer, format="PNG")
    upload = await client.post(
        f"{API}/media",
        files={"file": ("meal.png", buffer.getvalue(), "image/png")},
        headers=headers,
    )
    return data_of(upload)


async def test_post_price_tags_and_store_location(client):
    """人均价格、口味标签与店铺坐标能写入并在详情中返回。"""
    seeded = data_of(await client.get(f"{API}/posts/p_1003"))
    assert seeded["avgPrice"] == 28
    assert seeded["tasteTags"] == ["咸鲜"]
    assert seeded["storeLocation"]["lat"] == 31.2305
    assert seeded["storeLocation"]["lng"] == 121.4737

    session = await login(client)
    headers = auth_headers(session["token"])
    media = await _upload_png(client, headers)
    body = {
        "title": "带标签的饭帖",
        "review": "微辣，很下饭。",
        "source": "takeaway",
        "imageAssetIds": [media["assetId"]],
        "takeawayStore": "测试小馆",
        "avgPrice": 35,
        "tasteTags": ["微辣", "重口下饭"],
        "storeLocation": {"lat": 31.2299, "lng": 121.4711, "poiId": "B0TEST001"},
        # 重复标签会被去重，保留用户选择的顺序。
        "location": {"lat": 31.2299, "lng": 121.4711, "area": "测试商圈", "publicConsent": True},
    }
    created = data_of(
        await client.post(
            f"{API}/posts",
            json=body,
            headers={**headers, "Idempotency-Key": "publish-tags-0001"},
        )
    )
    detail = data_of(await client.get(f"{API}/posts/{created['postId']}"))
    assert detail["avgPrice"] == 35
    assert detail["tasteTags"] == ["微辣", "重口下饭"]
    assert detail["storeLocation"] == {
        "lat": 31.2299,
        "lng": 121.4711,
        "poiId": "B0TEST001",
    }
    # 粗略位置只保留三位小数。
    assert detail["coarseArea"] == "测试商圈"


async def test_taste_tags_are_limited_and_validated(client):
    session = await login(client)
    headers = auth_headers(session["token"])
    base = {
        "title": "标签校验",
        "review": "验证标签数量和枚举。",
        "source": "self",
        "imageAssetIds": ["m_seed_1"],
    }
    too_many = await client.post(
        f"{API}/posts",
        json={**base, "tasteTags": ["清淡", "微辣", "特辣", "酸甜"]},
        headers={**headers, "Idempotency-Key": "publish-tags-0002"},
    )
    assert too_many.status_code == 422
    assert too_many.json()["code"] == "VALIDATION_FAILED"

    unknown = await client.post(
        f"{API}/posts",
        json={**base, "tasteTags": ["超级辣"]},
        headers={**headers, "Idempotency-Key": "publish-tags-0003"},
    )
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "VALIDATION_FAILED"


async def test_draft_create_update_and_publish(client):
    """草稿可以反复保存、不出现在公开列表，补全后才能发布。"""
    session = await login(client)
    headers = auth_headers(session["token"])

    draft = data_of(
        await client.post(
            f"{API}/posts/drafts",
            json={"title": "写到一半", "review": "", "imageAssetIds": []},
            headers=headers,
        )
    )
    assert draft["status"] == "draft"

    # 草稿不能通过公开详情访问。
    hidden = await client.get(f"{API}/posts/{draft['postId']}")
    assert hidden.status_code == 404

    drafts = data_of(await client.get(f"{API}/me/drafts", headers=headers))
    assert [item["id"] for item in drafts["items"]] == [draft["postId"]]

    # 编辑页需要拿到原始字段，而不是公开详情的裁剪结果。
    editable = data_of(
        await client.get(f"{API}/me/drafts/{draft['postId']}", headers=headers)
    )
    assert editable["title"] == "写到一半"
    assert editable["imageAssetIds"] == []
    assert editable["avgPrice"] is None
    assert editable["tasteTags"] == []

    media = await _upload_png(client, headers)
    updated = data_of(
        await client.put(
            f"{API}/posts/{draft['postId']}/draft",
            json={
                "title": "草稿补全",
                "review": "补上评价。",
                "source": "self",
                "imageAssetIds": [media["assetId"]],
                "avgPrice": 20,
                "tasteTags": ["清淡"],
            },
            headers=headers,
        )
    )
    assert updated["status"] == "draft"

    # 草稿内容不完整时仍然不能发布，发布必须走完整校验。
    incomplete = await client.post(
        f"{API}/posts/{draft['postId']}/publish",
        json={
            "title": "草稿补全",
            "review": "",
            "source": "self",
            "imageAssetIds": [media["assetId"]],
        },
        headers=headers,
    )
    assert incomplete.status_code == 422

    published = data_of(
        await client.post(
            f"{API}/posts/{draft['postId']}/publish",
            json={
                "title": "草稿补全",
                "review": "补上评价。",
                "source": "self",
                "imageAssetIds": [media["assetId"]],
                "avgPrice": 20,
                "tasteTags": ["清淡"],
            },
            headers=headers,
        )
    )
    assert published["status"] == "published"

    after = data_of(await client.get(f"{API}/me/drafts", headers=headers))
    assert after["items"] == []
    mine = data_of(await client.get(f"{API}/me/posts", headers=headers))
    assert mine["items"][0]["id"] == draft["postId"]

    # 已发布的草稿再次发布会得到明确的业务错误，而不是重复创建内容。
    again = await client.post(
        f"{API}/posts/{draft['postId']}/publish",
        json={
            "title": "草稿补全",
            "review": "补上评价。",
            "source": "self",
            "imageAssetIds": [media["assetId"]],
        },
        headers=headers,
    )
    assert again.status_code == 400
    assert again.json()["code"] == "POST_NOT_DRAFT"


async def test_delete_own_post_and_draft(client):
    """作者可以软删除自己的饭帖，删除后公开入口与我的发布都不再返回。"""
    session = await login(client)
    headers = auth_headers(session["token"])
    media = await _upload_png(client, headers)
    created = data_of(
        await client.post(
            f"{API}/posts",
            json={
                "title": "待删除",
                "review": "这条稍后会删掉。",
                "source": "self",
                "imageAssetIds": [media["assetId"]],
            },
            headers={**headers, "Idempotency-Key": "publish-delete-0001"},
        )
    )

    removed = data_of(
        await client.delete(f"{API}/posts/{created['postId']}", headers=headers)
    )
    assert removed["status"] == "deleted"
    assert removed["deletedAt"]

    assert (await client.get(f"{API}/posts/{created['postId']}")).status_code == 404
    mine = data_of(await client.get(f"{API}/me/posts", headers=headers))
    assert all(item["id"] != created["postId"] for item in mine["items"])

    # 重复删除返回 404，不会把删除时间刷新。
    second = await client.delete(f"{API}/posts/{created['postId']}", headers=headers)
    assert second.status_code == 404

    # 不能删除别人的饭帖，接口同样用 404 隐藏内容是否存在。
    others = await client.delete(f"{API}/posts/p_1001", headers=headers)
    assert others.status_code == 404

    # 草稿也支持直接删除。
    draft = data_of(
        await client.post(
            f"{API}/posts/drafts",
            json={"title": "废弃草稿"},
            headers=headers,
        )
    )
    deleted_draft = data_of(
        await client.delete(f"{API}/posts/{draft['postId']}", headers=headers)
    )
    assert deleted_draft["status"] == "deleted"
    drafts = data_of(await client.get(f"{API}/me/drafts", headers=headers))
    assert all(item["id"] != draft["postId"] for item in drafts["items"])


async def test_map_endpoints_require_key_and_login(client):
    """未配置地图 Key 时给出可降级的 503，而不是让客户端无限等待。"""
    config = data_of(await client.get(f"{API}/maps/config"))
    assert config["enabled"] is False

    anonymous = await client.get(f"{API}/maps/places", params={"keyword": "粉店"})
    assert anonymous.status_code == 401

    session = await login(client)
    headers = auth_headers(session["token"])
    places = await client.get(
        f"{API}/maps/places", params={"keyword": "粉店"}, headers=headers
    )
    assert places.status_code == 503
    assert places.json()["code"] == "MAP_NOT_CONFIGURED"

    static = await client.get(f"{API}/maps/static", params={"lat": 31.23, "lng": 121.47})
    assert static.status_code == 503
    assert static.json()["code"] == "MAP_NOT_CONFIGURED"


def test_tencent_place_response_parsing():
    """腾讯地点搜索的响应要映射成客户端统一的 name/address/lat/lng 字段。"""
    body = {
        "status": 0,
        "message": "query ok",
        "count": 3,
        "data": [
            {
                "id": "poi-1",
                "title": "老王牛肉粉",
                "address": "演示路 12 号",
                "location": {"lat": 31.2286, "lng": 121.469},
                "_distance": 320,
            },
            # 没有坐标的地点无法导航，应被跳过。
            {"id": "poi-2", "title": "没有坐标的店", "location": None},
            # 附近搜索也可能不返回距离，地址也可能缺失，字段要安全降级为空字符串。
            {
                "id": "poi-3",
                "title": "缺少距离的店",
                "address": None,
                "location": {"lat": 31.23, "lng": 121.47},
            },
        ],
    }
    items = parse_place_items(body)
    assert [item["id"] for item in items] == ["poi-1", "poi-3"]
    assert items[0] == {
        "id": "poi-1",
        "name": "老王牛肉粉",
        "address": "演示路 12 号",
        "lat": 31.2286,
        "lng": 121.469,
        "distanceMeters": 320,
    }
    assert items[1]["address"] == ""
    assert items[1]["distanceMeters"] is None


async def test_map_search_requires_location(monkeypatch):
    """没有定位时直接给出 400，避免腾讯“全国”范围返回空列表误导用户。"""
    from app.core.config import settings
    from app.core.errors import AppError
    from app.services.map_service import search_places

    monkeypatch.setattr(settings, "tencent_map_key", "test-key")
    try:
        await search_places("KFC")
    except AppError as error:
        assert error.code == "LOCATION_REQUIRED"
        assert error.status_code == 400
    else:
        raise AssertionError("没有定位时应当拒绝搜索")
