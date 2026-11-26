"""Langfuse 可观测接入的测试。

覆盖：
1. 调用事件构造：Trace + Generation、Token、成本、失败级别；
2. 指标接口解析：调用量、错误率、延迟、Token、成本、评分；
3. 提示词读取的降级与缓存，以及发布后缓存立即更新；
4. 未配置 Langfuse 时发布提示词返回 502，而不是 500；
5. 人工评分先落本地，未配置时标记“未同步”，详情接口能读到评分；
6. 模型配置的输入/输出单价可以保存并回显。
"""

from dataclasses import dataclass

from app.core.config import settings
from app.db.models import AICallLog, AICallScore
from app.main import app
from app.services import langfuse_service, prompt_service
from app.utils.time import now_utc
from tests.conftest import API, auth_headers, data_of
from tests.test_admin import login_as_admin


@dataclass
class FakeStep:
    step: str
    detail: str
    duration_ms: int = 0


def test_build_model_call_events_includes_cost_and_tokens():
    events = langfuse_service.build_model_call_events(
        call_log_id="ail_test1",
        request_id="req_1",
        subject_ref="guest:device",
        context_type="home",
        provider_name="DeepSeek",
        model="deepseek-chat",
        status="success",
        latency_ms=1200,
        prompt_tokens=1000,
        completion_tokens=500,
        total_tokens=1500,
        error_code=None,
        error_message=None,
        steps=[
            FakeStep(step="model_request", detail="完整的系统提示词与用户提示词"),
            FakeStep(step="model_response", detail="模型原始返回"),
        ],
        input_price_per_1k=0.5,
        output_price_per_1k=1.0,
        prompt_name="mealmate.chat.system",
        prompt_version=3,
    )
    assert [event["type"] for event in events] == [
        "trace-create",
        "generation-create",
    ]
    generation = events[1]["body"]
    assert generation["traceId"] == "ail_test1"
    assert generation["usageDetails"] == {"input": 1000, "output": 500, "total": 1500}
    # 1000 token × 0.5 美元/千 = 0.5；500 token × 1.0 美元/千 = 0.5。
    assert generation["costDetails"]["total"] == 1.0
    assert generation["promptName"] == "mealmate.chat.system"
    assert generation["promptVersion"] == 3
    assert generation["level"] == "DEFAULT"
    assert events[0]["body"]["metadata"]["callLogId"] == "ail_test1"


def test_build_model_call_events_marks_error_level():
    events = langfuse_service.build_model_call_events(
        call_log_id="ail_test2",
        request_id=None,
        subject_ref="user:1",
        context_type="post",
        provider_name="DeepSeek",
        model="deepseek-chat",
        status="failed",
        latency_ms=300,
        prompt_tokens=10,
        completion_tokens=0,
        total_tokens=10,
        error_code="AI_TIMEOUT",
        error_message="请求超时",
        steps=[],
    )
    generation = events[1]["body"]
    assert generation["level"] == "ERROR"
    assert generation["statusMessage"] == "请求超时"
    assert "costDetails" not in generation


async def test_fetch_metrics_parses_rows(monkeypatch):
    monkeypatch.setattr(settings, "langfuse_base_url", "http://fake.langfuse")
    monkeypatch.setattr(settings, "langfuse_public_key", "pk")
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk")
    calls: list[dict] = []

    async def fake_query(metrics, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return [
                {
                    "count_count": 10,
                    "avg_latency": 120.4,
                    "p95_latency": 300,
                    "sum_totalTokens": 1500,
                    "sum_totalCost": 0.12,
                }
            ]
        if len(calls) == 2:
            return [
                {
                    "time_dimension": "2026-11-25T00:00:00Z",
                    "count_count": 4,
                    "avg_latency": 100,
                    "sum_totalTokens": 600,
                    "sum_totalCost": 0.05,
                },
                {
                    "time_dimension": "2026-11-26T00:00:00Z",
                    "count_count": 6,
                    "avg_latency": 140,
                    "sum_totalTokens": 900,
                    "sum_totalCost": 0.07,
                },
            ]
        if len(calls) == 3:
            return [{"time_dimension": "2026-11-26T00:00:00Z", "count_count": 1}]
        return [{"avg_value": 4.25, "count_count": 8}]

    monkeypatch.setattr(langfuse_service, "_metrics_query", fake_query)
    data = await langfuse_service.fetch_metrics(7)
    assert data["configured"] is True
    assert data["summary"]["calls"] == 10
    assert data["summary"]["errors"] == 1
    assert data["summary"]["errorRate"] == 0.1
    assert data["summary"]["totalTokens"] == 1500
    assert data["summary"]["totalCost"] == 0.12
    assert len(data["trend"]) == 2
    assert data["trend"][0]["date"] == "2026-11-25"
    assert data["scores"] == {"count": 8, "average": 4.25}


async def test_prompt_falls_back_and_caches(client, monkeypatch):
    prompt_service._cache.clear()
    monkeypatch.setattr(settings, "langfuse_base_url", "")
    monkeypatch.setattr(settings, "langfuse_public_key", "")
    monkeypatch.setattr(settings, "langfuse_secret_key", "")
    async with app.state.test_session_factory() as db:
        local = await prompt_service.get_prompt(db, "mealmate.chat.system")
    assert local.source == "default"
    assert local.version is None
    assert local.text

    monkeypatch.setattr(settings, "langfuse_base_url", "http://fake.langfuse")
    monkeypatch.setattr(settings, "langfuse_public_key", "pk")
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk")
    prompt_service._cache.clear()
    calls = {"count": 0}

    async def fake_fetch(name, label="production"):
        calls["count"] += 1
        return {"prompt": "远程提示词", "version": 3}

    monkeypatch.setattr(langfuse_service, "fetch_prompt", fake_fetch)
    async with app.state.test_session_factory() as db:
        first = await prompt_service.get_prompt(db, "mealmate.chat.system")
        second = await prompt_service.get_prompt(db, "mealmate.chat.system")
    assert first.source == "langfuse"
    assert first.text == "远程提示词"
    assert first.version == 3
    assert second.text == "远程提示词"
    # 第二次直接命中缓存，不再请求 Langfuse。
    assert calls["count"] == 1
    prompt_service._cache.clear()


async def test_local_prompt_publish_without_langfuse(client, monkeypatch):
    """没有 Langfuse 也能发布、读取和查看历史版本。"""
    prompt_service._cache.clear()
    monkeypatch.setattr(settings, "langfuse_base_url", "")
    monkeypatch.setattr(settings, "langfuse_public_key", "")
    monkeypatch.setattr(settings, "langfuse_secret_key", "")
    token = await login_as_admin(client)
    headers = auth_headers(token)

    first = await client.post(
        f"{API}/admin/prompts/mealmate.chat.system/publish",
        json={"content": "本地第一版提示词", "commitMessage": "初始化"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert data_of(first)["version"] == 1

    second = await client.post(
        f"{API}/admin/prompts/mealmate.chat.system/publish",
        json={"content": "本地第二版提示词"},
        headers=headers,
    )
    assert data_of(second)["version"] == 2

    listed = await client.get(f"{API}/admin/prompts", headers=headers)
    item = next(
        row
        for row in data_of(listed)["items"]
        if row["name"] == "mealmate.chat.system"
    )
    assert item["source"] == "local"
    assert item["version"] == 2
    assert item["content"] == "本地第二版提示词"
    assert item["versions"] == [2, 1]

    versions = await client.get(
        f"{API}/admin/prompts/mealmate.chat.system/versions", headers=headers
    )
    rows = data_of(versions)["items"]
    assert [row["version"] for row in rows] == [2, 1]
    # 旧版本归档，只有最新一版带 production 标签。
    assert rows[0]["labels"] == ["production"]
    assert rows[1]["labels"] == []

    async with app.state.test_session_factory() as db:
        snapshot = await prompt_service.get_prompt(db, "mealmate.chat.system")
    assert snapshot.source == "local"
    assert snapshot.version == 2
    assert snapshot.text == "本地第二版提示词"
    prompt_service._cache.clear()


async def test_local_metrics_without_langfuse(client):
    """本地指标不依赖 Langfuse，直接聚合调用日志与评分。"""
    token = await login_as_admin(client)
    headers = auth_headers(token)
    async with app.state.test_session_factory() as db:
        db.add(
            AICallLog(
                id="ail_metric_ok",
                subject_ref="user:test",
                context_type="home",
                provider_name="DeepSeek",
                model="deepseek-chat",
                status="success",
                latency_ms=100,
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd=0.02,
                prompt_name="mealmate.chat.system",
                prompt_version=2,
                prompt_source="local",
                created_at=now_utc(),
            )
        )
        db.add(
            AICallLog(
                id="ail_metric_fail",
                subject_ref="user:test",
                context_type="home",
                provider_name="DeepSeek",
                model="deepseek-chat",
                status="failed",
                latency_ms=300,
                prompt_tokens=20,
                completion_tokens=0,
                total_tokens=20,
                cost_usd=0.001,
                prompt_name="mealmate.chat.system",
                prompt_version=2,
                prompt_source="local",
                created_at=now_utc(),
            )
        )
        db.add(
            AICallScore(
                id="score_metric",
                call_log_id="ail_metric_ok",
                score=5,
                comment=None,
                scorer_name="测试管理员",
                source="manual",
                langfuse_synced=False,
                created_at=now_utc(),
            )
        )
        await db.commit()

    response = await client.get(
        f"{API}/admin/ai-metrics?days=7", headers=headers
    )
    payload = data_of(response)
    assert payload["source"] == "local"
    assert payload["summary"]["calls"] == 2
    assert payload["summary"]["errors"] == 1
    assert payload["summary"]["errorRate"] == 0.5
    assert payload["summary"]["totalTokens"] == 170
    assert payload["summary"]["totalCost"] == 0.021
    assert payload["summary"]["p95LatencyMs"] == 100
    assert payload["scores"]["average"] == 5
    assert payload["prompts"][0]["version"] == 2
    assert payload["prompts"][0]["calls"] == 2
    assert payload["prompts"][0]["errors"] == 1


async def test_call_score_saved_locally_without_langfuse(client):
    token = await login_as_admin(client)
    headers = auth_headers(token)
    async with app.state.test_session_factory() as db:
        db.add(
            AICallLog(
                id="ail_score_1",
                subject_ref="user:test",
                context_type="home",
                provider_name="DeepSeek",
                model="deepseek-chat",
                status="success",
                latency_ms=120,
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                created_at=now_utc(),
            )
        )
        await db.commit()

    created = await client.post(
        f"{API}/admin/ai-call-logs/ail_score_1/scores",
        json={"score": 4, "comment": "推荐准确，略长"},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    payload = data_of(created)
    assert payload["score"] == 4
    assert payload["langfuseSynced"] is False

    listed = await client.get(
        f"{API}/admin/ai-call-logs/ail_score_1/scores", headers=headers
    )
    assert data_of(listed)["items"][0]["comment"] == "推荐准确，略长"

    detail = await client.get(
        f"{API}/admin/ai-call-logs/ail_score_1", headers=headers
    )
    assert data_of(detail)["scores"][0]["score"] == 4

    missing = await client.post(
        f"{API}/admin/ai-call-logs/not-exist/scores",
        json={"score": 5},
        headers=headers,
    )
    assert missing.status_code == 404


async def test_provider_price_fields_round_trip(client):
    token = await login_as_admin(client)
    headers = auth_headers(token)
    created = await client.post(
        f"{API}/admin/ai-providers",
        json={
            "name": "带单价的模型",
            "providerType": "openai_compatible",
            "baseUrl": "https://api.example.com/v1",
            "apiKey": "sk-price",
            "model": "example-chat",
            "inputPricePer1k": 0.14,
            "outputPricePer1k": 0.28,
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    payload = data_of(created)
    assert payload["inputPricePer1k"] == 0.14
    assert payload["outputPricePer1k"] == 0.28

    listed = await client.get(f"{API}/admin/ai-providers", headers=headers)
    row = next(
        item for item in data_of(listed)["items"] if item["id"] == payload["id"]
    )
    assert row["outputPricePer1k"] == 0.28
