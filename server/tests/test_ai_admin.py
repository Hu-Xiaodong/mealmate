"""AI 模型配置、调用日志与自动分配的接口测试。

覆盖：
1. 后台可以新增、编辑、删除模型配置，密钥只返回掩码；
2. 编辑时不填密钥不会覆盖原密钥，数据库里保存的是密文；
3. 测试连接会真实调用一次模型（用例中替换为假实现）并写回结果；
4. 自动分配按优先级切换：第一个失败会尝试第二个；
5. 模型返回不存在的菜谱编号会被拒绝，并记录失败日志；
6. 全部模型失败时回退到本地规则推荐，不编造内容。
"""

import json

from sqlalchemy import select

from app.core.security import decrypt_secret
from app.db.models import AICallLog, AIProvider
from app.main import app
from app.services.ai_service import AICallError, ModelCallResult
from tests.conftest import API, auth_headers, data_of
from tests.test_admin import ADMIN_PASSWORD, create_admin, login_as_admin

PROVIDER_BODY = {
    "name": "DeepSeek 主力",
    "providerType": "openai_compatible",
    "baseUrl": "https://api.deepseek.com/v1",
    "apiKey": "sk-test-1234567890",
    "model": "deepseek-chat",
    "enabled": True,
    "priority": 10,
    "timeoutSeconds": 20,
    "maxOutputTokens": 800,
}


async def _create_provider(client, headers, **overrides) -> dict:
    body = {**PROVIDER_BODY, **overrides}
    response = await client.post(
        f"{API}/admin/ai-providers", json=body, headers=headers
    )
    assert response.status_code == 200, response.text
    return data_of(response)


async def test_provider_crud_masks_and_keeps_secret(client):
    token = await login_as_admin(client)
    headers = auth_headers(token)

    created = await _create_provider(client, headers)
    provider_id = created["id"]
    assert created["apiKeyMasked"] == "sk-t****7890"
    assert "sk-test-1234567890" not in json.dumps(created, ensure_ascii=False)

    # 数据库只保存密文，即使直接读库也拿不到明文。
    async with app.state.test_session_factory() as db:
        stored = await db.scalar(select(AIProvider).where(AIProvider.id == provider_id))
        assert stored is not None
        assert stored.api_key_encrypted != "sk-test-1234567890"
        assert decrypt_secret(stored.api_key_encrypted) == "sk-test-1234567890"

    # 编辑时留空 apiKey：模型名可以改，原密钥必须保留。
    updated = await client.put(
        f"{API}/admin/ai-providers/{provider_id}",
        json={"model": "deepseek-reasoner", "apiKey": ""},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert data_of(updated)["model"] == "deepseek-reasoner"
    assert data_of(updated)["apiKeyMasked"] == "sk-t****7890"

    async with app.state.test_session_factory() as db:
        stored = await db.scalar(select(AIProvider).where(AIProvider.id == provider_id))
        assert decrypt_secret(stored.api_key_encrypted) == "sk-test-1234567890"

    # 名称唯一，重复新增返回 409。
    duplicate = await client.post(
        f"{API}/admin/ai-providers", json=PROVIDER_BODY, headers=headers
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "AI_PROVIDER_NAME_EXISTS"

    listed = await client.get(f"{API}/admin/ai-providers", headers=headers)
    assert listed.status_code == 200
    assert "sk-test-1234567890" not in listed.text
    assert len(data_of(listed)["items"]) == 1

    removed = await client.delete(
        f"{API}/admin/ai-providers/{provider_id}", headers=headers
    )
    assert removed.status_code == 200
    listed = await client.get(f"{API}/admin/ai-providers", headers=headers)
    assert data_of(listed)["items"] == []


async def test_provider_requires_ai_config_permission(client):
    await create_admin("content01", ADMIN_PASSWORD, "content_operator")
    login = await client.post(
        f"{API}/admin/auth/login",
        json={"username": "content01", "password": ADMIN_PASSWORD},
    )
    assert login.status_code == 200, login.text
    headers = auth_headers(data_of(login)["token"])

    denied = await client.get(f"{API}/admin/ai-providers", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["code"] == "ADMIN_PERMISSION_DENIED"


async def test_provider_test_connection_updates_result(client, monkeypatch):
    token = await login_as_admin(client)
    headers = auth_headers(token)
    provider = await _create_provider(client, headers)

    async def fake_success(provider_obj, system_prompt, user_prompt):
        return ModelCallResult(text="可用", latency_ms=36, prompt_tokens=12, total_tokens=14)

    monkeypatch.setattr("app.services.ai_service._invoke_model", fake_success)
    response = await client.post(
        f"{API}/admin/ai-providers/{provider['id']}/test", headers=headers
    )
    assert response.status_code == 200, response.text
    result = data_of(response)
    assert result["ok"] is True
    assert result["message"] == "可用"

    listed = await client.get(f"{API}/admin/ai-providers", headers=headers)
    item = data_of(listed)["items"][0]
    assert item["lastTestOk"] is True
    assert item["lastTestMessage"] == "可用"

    async def fake_failure(provider_obj, system_prompt, user_prompt):
        raise AICallError("PROVIDER_HTTP_401", "Authentication Fails", latency_ms=18)

    monkeypatch.setattr("app.services.ai_service._invoke_model", fake_failure)
    failed = await client.post(
        f"{API}/admin/ai-providers/{provider['id']}/test", headers=headers
    )
    assert failed.status_code == 200
    assert data_of(failed)["ok"] is False
    assert data_of(failed)["errorCode"] == "PROVIDER_HTTP_401"

    listed = await client.get(f"{API}/admin/ai-providers", headers=headers)
    assert data_of(listed)["items"][0]["lastTestOk"] is False


async def test_chat_switches_provider_by_priority_and_logs(client, monkeypatch):
    token = await login_as_admin(client)
    headers = auth_headers(token)
    await _create_provider(client, headers, name="模型甲", priority=10)
    await _create_provider(client, headers, name="模型乙", priority=20)

    calls: list[str] = []

    async def fake_invoke(provider, system_prompt, user_prompt):
        calls.append(provider.name)
        if provider.name == "模型甲":
            raise AICallError("PROVIDER_TIMEOUT", "请求超时", latency_ms=5000)
        return ModelCallResult(
            text=json.dumps(
                {
                    "reply": "给你一道十五分钟能做完的菜。",
                    "constraints": {},
                    "recipeIds": ["r_101", "r_missing"],
                    "reasons": {"r_101": "十五分钟搞定"},
                },
                ensure_ascii=False,
            ),
            latency_ms=42,
            prompt_tokens=180,
            completion_tokens=60,
            total_tokens=240,
        )

    monkeypatch.setattr("app.services.ai_service._invoke_model", fake_invoke)
    response = await client.post(
        f"{API}/ai/chat",
        json={"message": "下班只有十五分钟，能做什么？"},
        headers={"X-Device-Id": "guest-ai-routing"},
    )
    assert response.status_code == 200, response.text
    data = data_of(response)
    assert calls == ["模型甲", "模型乙"]
    assert data["origin"] == "ai_reference"
    assert [item["targetId"] for item in data["recommendations"]] == ["r_101"]
    assert "给你一道十五分钟能做完的菜" in data["message"]
    assert "AI 只做筛选和解释" in data["message"]

    logs = await client.get(f"{API}/admin/ai-call-logs?limit=10", headers=headers)
    assert logs.status_code == 200, logs.text
    items = data_of(logs)["items"]
    by_provider = {item["providerName"]: item for item in items}
    assert set(by_provider) == {"模型甲", "模型乙"}
    assert by_provider["模型甲"]["status"] == "failed"
    assert by_provider["模型甲"]["errorCode"] == "PROVIDER_TIMEOUT"
    assert by_provider["模型乙"]["status"] == "success"
    assert by_provider["模型乙"]["totalTokens"] == 240


async def test_chat_rejects_unknown_recipe_ids_then_falls_back(client, monkeypatch):
    token = await login_as_admin(client)
    headers = auth_headers(token)
    await _create_provider(client, headers)

    async def fake_invoke(provider, system_prompt, user_prompt):
        return ModelCallResult(
            text=json.dumps(
                {
                    "reply": "这道菜很适合你。",
                    "constraints": {},
                    "recipeIds": ["r_does_not_exist"],
                    "reasons": {},
                },
                ensure_ascii=False,
            ),
            latency_ms=20,
        )

    monkeypatch.setattr("app.services.ai_service._invoke_model", fake_invoke)
    response = await client.post(
        f"{API}/ai/chat",
        json={"message": "只有十五分钟"},
        headers={"X-Device-Id": "guest-ai-invalid"},
    )
    assert response.status_code == 200, response.text
    data = data_of(response)
    # 模型引用了不存在的菜谱，回复被丢弃，改用本地规则推荐真实菜谱。
    assert "AI 服务暂时不可用" in data["message"]
    assert data["recommendations"]
    assert all(item["targetId"].startswith("r_") for item in data["recommendations"])

    async with app.state.test_session_factory() as db:
        log = (
            await db.scalars(
                select(AICallLog).where(AICallLog.context_type == "home")
            )
        ).first()
        assert log is not None
        assert log.status == "failed"
        assert log.error_code == "AI_RECIPE_INVALID"


async def test_chat_falls_back_when_all_providers_fail(client, monkeypatch):
    token = await login_as_admin(client)
    headers = auth_headers(token)
    await _create_provider(client, headers, name="唯一模型")

    async def fake_failure(provider, system_prompt, user_prompt):
        raise AICallError("PROVIDER_CONNECTION", "无法连接模型服务", latency_ms=8)

    monkeypatch.setattr("app.services.ai_service._invoke_model", fake_failure)
    response = await client.post(
        f"{API}/ai/chat",
        json={"message": "有什么十分钟能做完的？"},
        headers={"X-Device-Id": "guest-ai-all-fail"},
    )
    assert response.status_code == 200, response.text
    data = data_of(response)
    assert data["recommendations"]
    assert "AI 服务暂时不可用" in data["message"]

    logs = await client.get(f"{API}/admin/ai-call-logs", headers=headers)
    items = data_of(logs)["items"]
    assert len(items) == 1
    assert items[0]["status"] == "failed"
    assert items[0]["errorCode"] == "PROVIDER_CONNECTION"
