"""提示词变量：解析优先级、发布校验、删除保护与回滚。"""

from app.main import app
from app.services import prompt_service
from tests.conftest import API, auth_headers, data_of
from tests.test_admin import login_as_admin


async def _headers(client) -> dict[str, str]:
    token = await login_as_admin(client)
    return auth_headers(token)


async def test_shared_variable_renders_in_preview_and_runtime(client):
    headers = await _headers(client)
    saved = await client.post(
        f"{API}/admin/prompt-variables",
        json={
            "scope": "shared",
            "key": "brand_name",
            "value": "MealMate 小食堂",
            "defaultValue": "小食堂",
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text

    content = "你是 {{brand_name}} 的助手。"
    preview = await client.post(
        f"{API}/admin/prompts/mealmate.chat.system/preview",
        json={"content": content},
        headers=headers,
    )
    assert data_of(preview)["content"] == "你是 MealMate 小食堂 的助手。"
    assert data_of(preview)["missingKeys"] == []

    published = await client.post(
        f"{API}/admin/prompts/mealmate.chat.system/publish",
        json={"content": content},
        headers=headers,
    )
    assert published.status_code == 200, published.text

    listed = await client.get(f"{API}/admin/prompts", headers=headers)
    item = next(
        row
        for row in data_of(listed)["items"]
        if row["name"] == "mealmate.chat.system"
    )
    assert item["content"] == content
    assert item["preview"] == "你是 MealMate 小食堂 的助手。"


async def test_specific_value_wins_over_shared_and_default(client):
    headers = await _headers(client)
    await client.post(
        f"{API}/admin/prompt-variables",
        json={"scope": "shared", "key": "tone", "value": "共用语气"},
        headers=headers,
    )
    preview = await client.post(
        f"{API}/admin/prompts/mealmate.chat.system/preview",
        json={
            "content": "语气：{{tone}}",
            "variables": [
                {"key": "tone", "value": "专属语气", "defaultValue": "默认语气"}
            ],
        },
        headers=headers,
    )
    payload = data_of(preview)
    assert payload["content"] == "语气：专属语气"
    assert payload["sources"]["tone"] == "prompt"


async def test_missing_variable_blocks_publish(client):
    headers = await _headers(client)
    response = await client.post(
        f"{API}/admin/prompts/mealmate.chat.system/publish",
        json={"content": "必须包含 {{not_defined_key}}"},
        headers=headers,
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "AI_PROMPT_VARIABLE_MISSING"
    assert body["data"]["missingKeys"] == ["not_defined_key"]


async def test_delete_shared_variable_is_blocked_when_published_prompt_uses_it(client):
    headers = await _headers(client)
    published = await client.post(
        f"{API}/admin/prompts/mealmate.chat.system/publish",
        json={"content": "推荐数量 {{max_recipes}}"},
        headers=headers,
    )
    assert published.status_code == 200, published.text

    listed = await client.get(f"{API}/admin/prompt-variables", headers=headers)
    shared = next(
        row
        for row in data_of(listed)["items"]
        if row["key"] == "max_recipes" and row["scope"] == "shared"
    )
    deleted = await client.delete(
        f"{API}/admin/prompt-variables/{shared['id']}", headers=headers
    )
    assert deleted.status_code == 409, deleted.text
    assert deleted.json()["code"] == "AI_PROMPT_VARIABLE_IN_USE"


async def test_specific_override_allows_deleting_shared_variable(client):
    headers = await _headers(client)
    await client.post(
        f"{API}/admin/prompt-variables",
        json={"scope": "shared", "key": "brand", "value": "共用品牌"},
        headers=headers,
    )
    published = await client.post(
        f"{API}/admin/prompts/mealmate.chat.system/publish",
        json={
            "content": "品牌：{{brand}}",
            "variables": [{"key": "brand", "value": "专属品牌"}],
        },
        headers=headers,
    )
    assert published.status_code == 200, published.text

    listed = await client.get(f"{API}/admin/prompt-variables", headers=headers)
    shared = next(
        row
        for row in data_of(listed)["items"]
        if row["key"] == "brand" and row["scope"] == "shared"
    )
    deleted = await client.delete(
        f"{API}/admin/prompt-variables/{shared['id']}", headers=headers
    )
    assert deleted.status_code == 200, deleted.text


async def test_prompt_specific_edit_is_draft_until_publish(client):
    """变量管理页改专属变量只改草稿，线上仍使用发布快照。"""
    prompt_service._cache.clear()
    headers = await _headers(client)
    published = await client.post(
        f"{API}/admin/prompts/mealmate.chat.system/publish",
        json={
            "content": "语气 {{tone}}",
            "variables": [{"key": "tone", "value": "已发布语气"}],
        },
        headers=headers,
    )
    assert published.status_code == 200, published.text

    saved = await client.post(
        f"{API}/admin/prompt-variables",
        json={
            "scope": "prompt",
            "promptName": "mealmate.chat.system",
            "key": "tone",
            "value": "草稿语气",
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text

    async with app.state.test_session_factory() as db:
        snapshot = await prompt_service.get_prompt(db, "mealmate.chat.system")
    assert snapshot.text == "语气 已发布语气"

    listed = await client.get(f"{API}/admin/prompts", headers=headers)
    item = next(
        row
        for row in data_of(listed)["items"]
        if row["name"] == "mealmate.chat.system"
    )
    assert item["preview"] == "语气 已发布语气"
    assert item["variables"] == [
        {"key": "tone", "value": "草稿语气", "defaultValue": None}
    ]
    prompt_service._cache.clear()


async def test_rollback_restores_prompt_specific_variables(client):
    headers = await _headers(client)
    first = await client.post(
        f"{API}/admin/prompts/mealmate.chat.system/publish",
        json={
            "content": "第一版 {{tone}}",
            "variables": [{"key": "tone", "value": "第一版语气"}],
        },
        headers=headers,
    )
    assert data_of(first)["version"] == 1

    second = await client.post(
        f"{API}/admin/prompts/mealmate.chat.system/publish",
        json={
            "content": "第二版 {{tone}}",
            "variables": [{"key": "tone", "value": "第二版语气"}],
        },
        headers=headers,
    )
    assert data_of(second)["version"] == 2

    rolled = await client.post(
        f"{API}/admin/prompts/mealmate.chat.system/rollback",
        json={"version": 1},
        headers=headers,
    )
    assert rolled.status_code == 200, rolled.text
    assert data_of(rolled)["version"] == 3

    listed = await client.get(f"{API}/admin/prompts", headers=headers)
    item = next(
        row
        for row in data_of(listed)["items"]
        if row["name"] == "mealmate.chat.system"
    )
    assert item["content"] == "第一版 {{tone}}"
    assert item["variables"] == [
        {"key": "tone", "value": "第一版语气", "defaultValue": None}
    ]
    assert item["preview"] == "第一版 第一版语气"

    async with app.state.test_session_factory() as db:
        snapshot = await prompt_service.get_prompt(db, "mealmate.chat.system")
    assert snapshot.text == "第一版 第一版语气"
    assert snapshot.version == 3
    prompt_service._cache.clear()
