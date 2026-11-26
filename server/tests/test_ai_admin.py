"""AI 模型配置、调用日志与自动分配的接口测试。

覆盖：
1. 后台可以新增、编辑、删除模型配置，密钥只返回掩码；
2. 编辑时不填密钥不会覆盖原密钥，数据库里保存的是密文；
3. 测试连接会真实调用一次模型（用例中替换为假实现）并写回结果；
4. 同一用途只能启用一个模型：启用新模型会自动停用同类型旧模型；
5. 模型返回不存在的菜谱编号会被拒绝，并记录失败日志；
6. 启用模型调用失败时回退到本地规则推荐，不编造内容；
7. 调用详情接口返回完整执行过程，失败后追加回退步骤，并沿用日志查看权限。
"""

import json

from sqlalchemy import select

from app.core.security import decrypt_secret
from app.db.models import AICallLog, AIProvider
from app.main import app
from app.services.ai_service import AICallError, ModelCallResult
from app.services.embedding_service import EmbeddingError
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


async def test_embedding_provider_test_connection_uses_embeddings(client, monkeypatch):
    """嵌入用途的“测试连接”必须调用嵌入接口，而不是聊天接口。"""
    token = await login_as_admin(client)
    headers = auth_headers(token)
    provider = await _create_provider(
        client,
        headers,
        name="嵌入模型",
        kind="embedding",
        dimensions=1024,
        baseUrl="https://api.siliconflow.cn/v1",
        model="BAAI/bge-m3",
    )

    async def fake_embedding(provider_obj, texts):
        return [[0.0] * 1024 for _ in texts], 7

    monkeypatch.setattr(
        "app.services.embedding_service._request_embeddings", fake_embedding
    )
    response = await client.post(
        f"{API}/admin/ai-providers/{provider['id']}/test", headers=headers
    )
    assert response.status_code == 200, response.text
    result = data_of(response)
    assert result["ok"] is True
    assert "1024 维" in result["message"]

    async def fake_missing_endpoint(provider_obj, texts):
        raise EmbeddingError(
            "EMBEDDING_HTTP_404",
            "嵌入模型「嵌入模型」（BAAI/bge-m3）返回 HTTP 404：该地址没有嵌入接口",
        )

    monkeypatch.setattr(
        "app.services.embedding_service._request_embeddings", fake_missing_endpoint
    )
    failed = await client.post(
        f"{API}/admin/ai-providers/{provider['id']}/test", headers=headers
    )
    assert failed.status_code == 200
    assert data_of(failed)["ok"] is False
    assert data_of(failed)["errorCode"] == "EMBEDDING_HTTP_404"


async def test_only_one_model_per_kind_can_be_enabled(client, monkeypatch):
    """同一用途只能启用一个模型，调用时固定使用启用的那个。

    产品要求模型列表提供开关，并且聊天、嵌入两类各自最多开一个。
    因此新增或启用一个模型时，后端会自动停用同类型的其他模型；
    调用 AI 时读取的是启用中的那一个，而不是按优先级挨个尝试。
    """
    token = await login_as_admin(client)
    headers = auth_headers(token)
    first = await _create_provider(client, headers, name="模型甲", priority=10)
    await _create_provider(client, headers, name="模型乙", priority=20)

    async def enabled_map() -> dict[str, bool]:
        listed = await client.get(f"{API}/admin/ai-providers", headers=headers)
        assert listed.status_code == 200, listed.text
        return {
            item["name"]: item["enabled"]
            for item in data_of(listed)["items"]
            if item["kind"] == "chat"
        }

    # 后创建的模型默认启用，先前启用的同类型模型被自动停用。
    assert await enabled_map() == {"模型甲": False, "模型乙": True}

    calls: list[str] = []

    async def fake_invoke(provider, system_prompt, user_prompt):
        calls.append(provider.name)
        return ModelCallResult(
            text=json.dumps(
                {
                    "reply": "给你一道十五分钟能做完的菜。",
                    "constraints": {},
                    "recipeIds": ["r_101"],
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
        headers={"X-Device-Id": "guest-ai-single-enabled"},
    )
    assert response.status_code == 200, response.text
    # 只调用启用中的模型乙，不再尝试已停用的模型甲。
    assert calls == ["模型乙"]
    data = data_of(response)
    assert [item["targetId"] for item in data["recommendations"]] == ["r_101"]

    # 再切回模型甲：模型乙自动停用，下一次问答只调用模型甲。
    switched = await client.put(
        f"{API}/admin/ai-providers/{first['id']}",
        json={"enabled": True},
        headers=headers,
    )
    assert switched.status_code == 200, switched.text
    assert await enabled_map() == {"模型甲": True, "模型乙": False}

    second_call = await client.post(
        f"{API}/ai/chat",
        json={"message": "再推荐一道菜"},
        headers={"X-Device-Id": "guest-ai-single-enabled-2"},
    )
    assert second_call.status_code == 200, second_call.text
    assert calls == ["模型乙", "模型甲"]


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


async def test_chat_ignores_embedding_provider(client, monkeypatch):
    """嵌入模型不能拿来聊天：即使优先级更高，也必须被跳过。"""
    token = await login_as_admin(client)
    headers = auth_headers(token)
    await _create_provider(
        client,
        headers,
        name="嵌入模型",
        kind="embedding",
        dimensions=1024,
        priority=5,
    )
    await _create_provider(client, headers, name="聊天模型", priority=10)

    calls: list[str] = []

    async def fake_invoke(provider, system_prompt, user_prompt):
        calls.append(provider.name)
        return ModelCallResult(
            text=json.dumps(
                {
                    "reply": "给你推荐一道快手菜。",
                    "constraints": {},
                    "recipeIds": ["r_101"],
                    "reasons": {"r_101": "十五分钟搞定"},
                },
                ensure_ascii=False,
            ),
            latency_ms=30,
        )

    monkeypatch.setattr("app.services.ai_service._invoke_model", fake_invoke)
    response = await client.post(
        f"{API}/ai/chat",
        json={"message": "十五分钟能做什么"},
        headers={"X-Device-Id": "guest-ai-kind-filter"},
    )
    assert response.status_code == 200, response.text
    assert calls == ["聊天模型"]


async def test_chat_history_is_included_in_prompt(client, monkeypatch):
    """客户端带来的最近对话必须进入提示词，模型才能理解追问。"""
    token = await login_as_admin(client)
    headers = auth_headers(token)
    await _create_provider(client, headers)

    prompts: list[str] = []

    async def fake_invoke(provider, system_prompt, user_prompt):
        prompts.append(user_prompt)
        return ModelCallResult(
            text=json.dumps(
                {
                    "reply": "换成鸡肉也可以。",
                    "constraints": {},
                    "recipeIds": [],
                    "reasons": {},
                },
                ensure_ascii=False,
            ),
            latency_ms=30,
        )

    monkeypatch.setattr("app.services.ai_service._invoke_model", fake_invoke)
    response = await client.post(
        f"{API}/ai/chat",
        json={
            "message": "那换成鸡肉呢",
            "history": [
                {"role": "user", "content": "番茄炒蛋怎么做"},
                {"role": "assistant", "content": "先炒鸡蛋，再炒番茄。"},
            ],
        },
        headers={"X-Device-Id": "guest-ai-history"},
    )
    assert response.status_code == 200, response.text
    assert prompts
    assert "最近对话" in prompts[0]
    assert "用户：番茄炒蛋怎么做" in prompts[0]
    assert "助手：先炒鸡蛋，再炒番茄。" in prompts[0]
    # 一般性问题允许 recipeIds 为空，不再强制推荐菜谱。
    assert data_of(response)["recommendations"] == []
    assert "换成鸡肉也可以" in data_of(response)["message"]


async def test_chat_stream_returns_deltas_and_cards(client, monkeypatch):
    """流式接口要按 SSE 逐段返回 reply，最后再给推荐卡片。"""
    token = await login_as_admin(client)
    headers = auth_headers(token)
    await _create_provider(client, headers, name="流式模型")

    async def fake_stream(provider, system_prompt, user_prompt, stats):
        stats.latency_ms = 25
        for piece in [
            "<reply>\n先切",
            "番茄，再炒鸡蛋。\n</reply>\n<recipes>r_101</recipes>",
            "\n<reasons>r_101=十五分钟搞定</reasons>",
        ]:
            yield piece

    monkeypatch.setattr("app.services.ai_service._stream_model", fake_stream)
    response = await client.post(
        f"{API}/ai/chat/stream",
        json={"message": "十五分钟能做什么"},
        headers={"X-Device-Id": "guest-ai-stream"},
    )
    assert response.status_code == 200, response.text
    body = response.text
    assert '"type": "status"' in body
    assert "先切" in body
    assert "番茄，再炒鸡蛋。" in body
    assert '"type": "done"' in body
    assert '"targetId": "r_101"' in body
    assert "AI 只做筛选和解释" in body


async def test_call_log_detail_returns_execution_trace(client, monkeypatch):
    """调用详情要能还原完整过程：上下文、提示词、原始输出、解析与校验。"""
    token = await login_as_admin(client)
    headers = auth_headers(token)
    await _create_provider(client, headers)

    async def fake_invoke(provider, system_prompt, user_prompt):
        return ModelCallResult(
            text=json.dumps(
                {
                    "reply": "十五分钟能做完的番茄炒蛋。",
                    "constraints": {},
                    "recipeIds": ["r_101"],
                    "reasons": {"r_101": "十五分钟搞定"},
                },
                ensure_ascii=False,
            ),
            latency_ms=35,
            prompt_tokens=120,
            completion_tokens=40,
            total_tokens=160,
        )

    monkeypatch.setattr("app.services.ai_service._invoke_model", fake_invoke)
    response = await client.post(
        f"{API}/ai/chat",
        json={"message": "只有十五分钟，能做什么？"},
        headers={"X-Device-Id": "guest-ai-detail"},
    )
    assert response.status_code == 200, response.text

    logs = await client.get(f"{API}/admin/ai-call-logs", headers=headers)
    item = data_of(logs)["items"][0]
    detail_response = await client.get(
        f"{API}/admin/ai-call-logs/{item['id']}", headers=headers
    )
    assert detail_response.status_code == 200, detail_response.text
    detail = data_of(detail_response)
    assert detail["id"] == item["id"]
    assert detail["status"] == "success"

    traces = detail["traces"]
    steps = [step["step"] for step in traces]
    # 开发者调试需要的阶段都要有记录，顺序固定，方便详情页合并成一份文本。
    assert steps == [
        "api_entry",
        "quota",
        "context_db",
        "context",
        "provider_selected",
        "prompt_built",
        "function_call",
        "http_request",
        "model_request",
        "model_response",
        "tool_calls",
        "output_parse",
        "validation",
    ]
    assert [step["seq"] for step in traces] == list(range(1, len(traces) + 1))

    function_step = next(step for step in traces if step["step"] == "function_call")
    assert "_invoke_model" in function_step["detail"]
    http_step = next(step for step in traces if step["step"] == "http_request")
    assert "POST" in http_step["detail"]
    assert "/chat/completions" in http_step["detail"]
    assert "Bearer" in http_step["detail"]
    request_step = next(step for step in traces if step["step"] == "model_request")
    assert "只有十五分钟" in request_step["detail"]
    response_step = next(step for step in traces if step["step"] == "model_response")
    assert "十五分钟能做完的番茄炒蛋" in response_step["detail"]
    # 项目没有接入 MCP、插件或函数调用，必须明确说明“未触发”，不能静默缺失。
    tool_step = next(step for step in traces if step["step"] == "tool_calls")
    assert "未接入 MCP" in tool_step["detail"]
    validation_step = next(step for step in traces if step["step"] == "validation")
    assert "r_101" in validation_step["detail"]


async def test_call_log_detail_records_failure_and_fallback(client, monkeypatch):
    """模型失败时详情要能回答“错误码是什么、之后产品做了什么”。"""
    token = await login_as_admin(client)
    headers = auth_headers(token)
    await _create_provider(client, headers, name="失败模型")

    async def fake_failure(provider, system_prompt, user_prompt):
        raise AICallError("PROVIDER_CONNECTION", "无法连接模型服务", latency_ms=8)

    monkeypatch.setattr("app.services.ai_service._invoke_model", fake_failure)
    response = await client.post(
        f"{API}/ai/chat",
        json={"message": "十分钟能做什么"},
        headers={"X-Device-Id": "guest-ai-detail-fail"},
    )
    assert response.status_code == 200, response.text
    assert "AI 服务暂时不可用" in data_of(response)["message"]

    logs = await client.get(f"{API}/admin/ai-call-logs", headers=headers)
    item = data_of(logs)["items"][0]
    assert item["status"] == "failed"
    detail = data_of(
        await client.get(f"{API}/admin/ai-call-logs/{item['id']}", headers=headers)
    )
    steps = [step["step"] for step in detail["traces"]]
    assert "model_error" in steps
    # 失败后追加了“回退本地规则”，排在时间线最后。
    assert steps[-1] == "fallback"
    error_step = next(step for step in detail["traces"] if step["step"] == "model_error")
    assert "PROVIDER_CONNECTION" in error_step["detail"]
    assert error_step["status"] == "failed"
    # 开发者调试需要看到请求参数和异常堆栈，而不只是一句错误信息。
    assert "异常堆栈" in error_step["detail"]
    http_step = next(
        step for step in detail["traces"] if step["step"] == "http_request"
    )
    assert "POST" in http_step["detail"]


async def test_call_log_detail_permission_and_missing(client):
    """详情沿用 ai.log.read 权限；不存在的编号返回 404。"""
    token = await login_as_admin(client)
    headers = auth_headers(token)

    missing = await client.get(
        f"{API}/admin/ai-call-logs/ail_not_exists", headers=headers
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "AI_CALL_LOG_NOT_FOUND"

    await create_admin("content02", ADMIN_PASSWORD, "content_operator")
    login = await client.post(
        f"{API}/admin/auth/login",
        json={"username": "content02", "password": ADMIN_PASSWORD},
    )
    assert login.status_code == 200, login.text
    denied = await client.get(
        f"{API}/admin/ai-call-logs/ail_not_exists",
        headers=auth_headers(data_of(login)["token"]),
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "ADMIN_PERMISSION_DENIED"


async def test_chat_history_is_limited(client):
    """历史最多 8 条，防止客户端把超长对话塞进提示词。"""
    response = await client.post(
        f"{API}/ai/chat",
        json={
            "message": "那换成鸡肉呢",
            "history": [
                {"role": "user", "content": f"第 {index} 轮"}
                for index in range(9)
            ],
        },
        headers={"X-Device-Id": "guest-ai-history-limit"},
    )
    assert response.status_code == 422


async def test_chat_stream_falls_back_when_model_fails(client, monkeypatch):
    """流式模型失败时仍然要给本地规则结果，不能只返回一个错误事件。"""
    token = await login_as_admin(client)
    headers = auth_headers(token)
    await _create_provider(client, headers, name="流式失败模型")

    async def fake_stream(provider, system_prompt, user_prompt, stats):
        raise AICallError("PROVIDER_CONNECTION", "无法连接模型服务", latency_ms=8)
        yield ""  # pragma: no cover - 让函数保持异步生成器形态

    monkeypatch.setattr("app.services.ai_service._stream_model", fake_stream)
    response = await client.post(
        f"{API}/ai/chat/stream",
        json={"message": "十分钟能做什么"},
        headers={"X-Device-Id": "guest-ai-stream-fail"},
    )
    assert response.status_code == 200, response.text
    assert "AI 服务暂时不可用" in response.text
    assert '"type": "done"' in response.text
    assert '"targetId"' in response.text
