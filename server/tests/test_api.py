"""核心 API 契约测试：覆盖 PRD 的浏览、登录、互动、发布、AI 配额主流程。"""

import io

from conftest import API, auth_headers, data_of, login
from PIL import Image

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
