"""AI 对话历史、摘要压缩、登录同步与清理的接口测试。

覆盖：
1. 问答返回真实的会话编号和消息编号，客户端本地记录才能与服务端对上；
2. 登录用户的历史落库，并能在下一轮不带历史时复用；
3. 30 分钟无操作自动开新会话；
4. 历史达到模型窗口 60% 时触发摘要压缩，摘要进入下一轮提示词；
5. 压缩失败回滚原历史，不影响本次问答；
6. 上下文窗口配置错误时自动砍半重试，并留下醒目的失败日志；
7. 登录后同步本地记录是幂等的，按客户端消息编号去重；
8. 每日清理按 30 天删会话、按 180 天删调用日志。
"""

import json
from datetime import timedelta

from sqlalchemy import func, select

from app.db.models import (
    AICallLog,
    AICallScore,
    AICallTrace,
    AIConversation,
    AIMessage,
)
from app.jobs.cleanup import purge_expired_call_logs
from app.main import app
from app.services.ai_history_service import (
    delete_user_ai_data,
    message_tokens,
    purge_expired_conversations,
    purge_orphan_conversations,
)
from app.services.ai_service import AICallError, ModelCallResult
from app.utils.time import now_utc
from tests.conftest import API, auth_headers, data_of, login
from tests.test_ai_admin import _create_provider, login_as_admin

CHAT_REPLY = {
    "reply": "十五分钟能做完的番茄炒蛋。",
    "constraints": {},
    "recipeIds": ["r_101"],
    "reasons": {"r_101": "十五分钟搞定"},
}


def _fake_chat_result() -> ModelCallResult:
    return ModelCallResult(
        text=json.dumps(CHAT_REPLY, ensure_ascii=False),
        latency_ms=30,
        prompt_tokens=120,
        completion_tokens=40,
        total_tokens=160,
    )


async def _seed_conversation(
    user_id: str,
    conversation_id: str,
    *,
    message_count: int = 12,
    content_chars: int = 200,
    last_active_at=None,
) -> str:
    """直接往测试库写一段会话，用于触发压缩和清理场景。

    为什么不用接口慢慢聊出 12 条消息：
    这样能精确控制消息长度和最后活动时间，测试意图更清楚，
    也不会因为模型回复文案变化而反复修改用例。
    """
    moment = last_active_at or now_utc()
    async with app.state.test_session_factory() as db:
        conversation = AIConversation(
            id=conversation_id,
            subject_ref=f"user:{user_id}",
            user_id=user_id,
            context_type="home",
            title="测试会话",
            summary=None,
            summary_message_count=0,
            message_count=message_count,
            last_active_at=moment,
            created_at=moment,
            updated_at=moment,
        )
        db.add(conversation)
        for index in range(message_count):
            content = ("快手菜" * (content_chars // 3)) + f"第{index}条"
            db.add(
                AIMessage(
                    id=f"aim_{conversation_id}_{index}",
                    conversation_id=conversation_id,
                    user_id=user_id,
                    client_message_id=f"cm_{conversation_id}_{index}",
                    role="user" if index % 2 == 0 else "assistant",
                    content=content,
                    token_estimate=message_tokens(content),
                    created_at=moment,
                )
            )
        await db.commit()
    return conversation_id


async def test_guest_chat_returns_conversation_and_message_ids(client, monkeypatch):
    """游客问答也要返回会话编号和消息编号。

    游客历史不落库，但本地记录需要编号才能：
    1. 登录后同步时去重；
    2. 区分同一句话的不同轮次。
    """
    token = await login_as_admin(client)
    headers = auth_headers(token)
    await _create_provider(client, headers)

    async def fake_invoke(provider, system_prompt, user_prompt):
        return _fake_chat_result()

    monkeypatch.setattr("app.services.ai_service._invoke_model", fake_invoke)
    response = await client.post(
        f"{API}/ai/chat",
        json={"message": "十五分钟能做什么", "messageId": "cm_guest_1"},
        headers={"X-Device-Id": "guest-history-ids"},
    )
    assert response.status_code == 200, response.text
    data = data_of(response)
    assert data["conversationId"].startswith("conv_")
    assert data["messageId"] == "cm_guest_1"
    assert data["replyMessageId"].startswith("cm_")


async def test_logged_in_chat_persists_history_and_dedupes(client, monkeypatch):
    """登录用户的历史要落库，下一轮不传 history 也能接上。"""
    admin_token = await login_as_admin(client)
    await _create_provider(client, auth_headers(admin_token))
    logged = await login(client, "13800000011")
    headers = auth_headers(logged["token"])
    user_id = logged["profile"]["accountId"]

    prompts: list[str] = []

    async def fake_invoke(provider, system_prompt, user_prompt):
        prompts.append(user_prompt)
        return _fake_chat_result()

    monkeypatch.setattr("app.services.ai_service._invoke_model", fake_invoke)

    first = await client.post(
        f"{API}/ai/chat",
        json={"message": "番茄炒蛋怎么做", "messageId": "cm_user_1"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    conversation_id = data_of(first)["conversationId"]
    assert data_of(first)["messageId"] == "cm_user_1"

    async with app.state.test_session_factory() as db:
        conversation = await db.get(AIConversation, conversation_id)
        assert conversation is not None
        assert conversation.user_id == user_id
        assert conversation.message_count == 2
        messages = (
            await db.scalars(
                select(AIMessage).where(AIMessage.conversation_id == conversation_id)
            )
        ).all()
        assert len(messages) == 2

    # 第二轮只带会话编号，不带 history：服务端必须从数据库恢复上一轮。
    second = await client.post(
        f"{API}/ai/chat",
        json={
            "conversationId": conversation_id,
            "message": "那换成鸡肉呢",
            "messageId": "cm_user_2",
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert data_of(second)["conversationId"] == conversation_id
    assert "用户：番茄炒蛋怎么做" in prompts[-1]
    assert "助手：" in prompts[-1]
    assert "那换成鸡肉呢" in prompts[-1]

    # 同一个 messageId 重试：用户消息不重复写入，只新增一条助手回答。
    third = await client.post(
        f"{API}/ai/chat",
        json={
            "conversationId": conversation_id,
            "message": "那换成鸡肉呢",
            "messageId": "cm_user_2",
        },
        headers=headers,
    )
    assert third.status_code == 200, third.text
    async with app.state.test_session_factory() as db:
        same_id_count = await db.scalar(
            select(func.count())
            .select_from(AIMessage)
            .where(
                AIMessage.conversation_id == conversation_id,
                AIMessage.client_message_id == "cm_user_2",
            )
        )
        assert same_id_count == 1
        conversation = await db.get(AIConversation, conversation_id)
        assert conversation.message_count == 5


async def test_idle_over_30_minutes_starts_new_conversation(client, monkeypatch):
    """超过 30 分钟无操作，再发消息要开新会话，旧会话保留在历史里。"""
    admin_token = await login_as_admin(client)
    await _create_provider(client, auth_headers(admin_token))
    logged = await login(client, "13800000012")
    headers = auth_headers(logged["token"])

    async def fake_invoke(provider, system_prompt, user_prompt):
        return _fake_chat_result()

    monkeypatch.setattr("app.services.ai_service._invoke_model", fake_invoke)
    first = await client.post(
        f"{API}/ai/chat",
        json={"message": "先问一句", "messageId": "cm_idle_1"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    old_id = data_of(first)["conversationId"]

    async with app.state.test_session_factory() as db:
        conversation = await db.get(AIConversation, old_id)
        conversation.last_active_at = now_utc() - timedelta(minutes=31)
        await db.commit()

    second = await client.post(
        f"{API}/ai/chat",
        json={
            "conversationId": old_id,
            "message": "过了半小时再问",
            "messageId": "cm_idle_2",
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert data_of(second)["conversationId"] != old_id

    async with app.state.test_session_factory() as db:
        total = await db.scalar(
            select(func.count())
            .select_from(AIConversation)
            .where(AIConversation.user_id == logged["profile"]["accountId"])
        )
        assert total == 2


async def test_history_compression_saves_summary(client, monkeypatch):
    """达到窗口 60% 时压缩旧消息，摘要进入下一轮提示词。"""
    admin_token = await login_as_admin(client)
    await _create_provider(
        client, auth_headers(admin_token), contextWindowTokens=1024
    )
    logged = await login(client, "13800000013")
    headers = auth_headers(logged["token"])
    user_id = logged["profile"]["accountId"]
    conversation_id = await _seed_conversation(user_id, "conv_compress_ok")

    prompts: list[str] = []
    summary_calls: list[str] = []

    async def fake_invoke(provider, system_prompt, user_prompt):
        if "对话摘要助手" in system_prompt:
            summary_calls.append(user_prompt)
            return ModelCallResult(text="用户想要快手菜，已推荐 r_101。", latency_ms=20)
        prompts.append(user_prompt)
        return _fake_chat_result()

    monkeypatch.setattr("app.services.ai_service._invoke_model", fake_invoke)
    response = await client.post(
        f"{API}/ai/chat",
        json={
            "conversationId": conversation_id,
            "message": "继续推荐",
            "messageId": "cm_compress_1",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert summary_calls, "应该调用一次摘要模型"
    assert "较早对话摘要" in prompts[-1]
    assert "用户想要快手菜" in prompts[-1]

    async with app.state.test_session_factory() as db:
        conversation = await db.get(AIConversation, conversation_id)
        assert conversation.summary == "用户想要快手菜，已推荐 r_101。"
        # 12 条消息、窗口 8 条，本次应压缩最旧的 4 条。
        assert conversation.summary_message_count == 4
        compress_log = await db.scalar(
            select(AICallLog).where(AICallLog.context_type == "history_compress")
        )
        assert compress_log is not None
        assert compress_log.status == "success"


async def test_compression_failure_keeps_original_history(client, monkeypatch):
    """压缩失败时摘要和消息保持原样，本次问答照常返回。"""
    admin_token = await login_as_admin(client)
    await _create_provider(
        client, auth_headers(admin_token), contextWindowTokens=1024
    )
    logged = await login(client, "13800000014")
    headers = auth_headers(logged["token"])
    user_id = logged["profile"]["accountId"]
    conversation_id = await _seed_conversation(user_id, "conv_compress_fail")

    async def fake_invoke(provider, system_prompt, user_prompt):
        if "对话摘要助手" in system_prompt:
            raise AICallError("PROVIDER_CONNECTION", "摘要服务连接失败", latency_ms=5)
        return _fake_chat_result()

    monkeypatch.setattr("app.services.ai_service._invoke_model", fake_invoke)
    response = await client.post(
        f"{API}/ai/chat",
        json={
            "conversationId": conversation_id,
            "message": "还能继续问吗",
            "messageId": "cm_compress_fail_1",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert "十五分钟能做完" in data_of(response)["message"]

    async with app.state.test_session_factory() as db:
        conversation = await db.get(AIConversation, conversation_id)
        assert conversation.summary is None
        assert conversation.summary_message_count == 0
        failed_log = await db.scalar(
            select(AICallLog).where(
                AICallLog.context_type == "history_compress",
                AICallLog.status == "failed",
            )
        )
        assert failed_log is not None
        assert failed_log.error_code == "PROVIDER_CONNECTION"


async def test_context_window_error_halves_and_retries(client, monkeypatch):
    """窗口填大导致超限时，自动砍半再压缩，并写醒目的配置错误日志。"""
    admin_token = await login_as_admin(client)
    await _create_provider(
        client, auth_headers(admin_token), contextWindowTokens=1024
    )
    logged = await login(client, "13800000015")
    headers = auth_headers(logged["token"])
    user_id = logged["profile"]["accountId"]
    conversation_id = await _seed_conversation(user_id, "conv_compress_window")

    summary_attempts = 0

    async def fake_invoke(provider, system_prompt, user_prompt):
        nonlocal summary_attempts
        if "对话摘要助手" in system_prompt:
            summary_attempts += 1
            if summary_attempts == 1:
                raise AICallError(
                    "PROVIDER_HTTP_400",
                    "This model's maximum context length is 4096 tokens",
                    latency_ms=6,
                )
            return ModelCallResult(text="砍半后生成的摘要。", latency_ms=20)
        return _fake_chat_result()

    monkeypatch.setattr("app.services.ai_service._invoke_model", fake_invoke)
    response = await client.post(
        f"{API}/ai/chat",
        json={
            "conversationId": conversation_id,
            "message": "继续",
            "messageId": "cm_compress_window_1",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert summary_attempts == 2, "第一次超限后应该砍半重试一次"

    async with app.state.test_session_factory() as db:
        conversation = await db.get(AIConversation, conversation_id)
        # 旧消息 4 条，砍半后只压缩最旧的 2 条。
        assert conversation.summary == "砍半后生成的摘要。"
        assert conversation.summary_message_count == 2
        config_log = await db.scalar(
            select(AICallLog).where(AICallLog.error_code == "AI_CONTEXT_WINDOW_INVALID")
        )
        assert config_log is not None
        assert config_log.status == "failed"
        assert "配置错误" in (config_log.error_message or "")
        trace = await db.scalar(
            select(AICallTrace).where(
                AICallTrace.call_log_id == config_log.id,
                AICallTrace.step == "context_window_error",
            )
        )
        assert trace is not None
        assert "配置错误" in trace.title


async def test_guest_conversation_reuses_redis_snapshot(client, monkeypatch):
    """游客在 Redis 可用时复用同一段会话，并刷新 30 分钟滑动过期时间。

    真实 Redis 不是测试依赖：这里用内存字典替换缓存读写，
    验证快照的序列化、归属校验、会话复用与 TTL 参数。
    """
    admin_token = await login_as_admin(client)
    await _create_provider(client, auth_headers(admin_token))

    store: dict[str, dict] = {}
    ttls: list[int] = []

    async def fake_get(key):
        return store.get(key)

    async def fake_set(key, value, ttl_seconds):
        store[key] = value
        ttls.append(ttl_seconds)

    async def fake_delete(key):
        store.pop(key, None)

    monkeypatch.setattr(
        "app.services.ai_history_service.cache.get_json", fake_get
    )
    monkeypatch.setattr(
        "app.services.ai_history_service.cache.set_json", fake_set
    )
    monkeypatch.setattr(
        "app.services.ai_history_service.cache.delete_key", fake_delete
    )

    prompts: list[str] = []

    async def fake_invoke(provider, system_prompt, user_prompt):
        prompts.append(user_prompt)
        return _fake_chat_result()

    monkeypatch.setattr("app.services.ai_service._invoke_model", fake_invoke)
    headers = {"X-Device-Id": "guest-redis-history"}

    first = await client.post(
        f"{API}/ai/chat",
        json={"message": "番茄炒蛋怎么做", "messageId": "cm_redis_1"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    conversation_id = data_of(first)["conversationId"]
    assert conversation_id.startswith("conv_")
    # 每次写入都带 30 分钟过期时间，这就是滑动过期。
    assert ttls and all(ttl == 1800 for ttl in ttls)
    assert any(key.endswith(conversation_id) for key in store)

    second = await client.post(
        f"{API}/ai/chat",
        json={
            "conversationId": conversation_id,
            "message": "那换成鸡肉呢",
            "messageId": "cm_redis_2",
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert data_of(second)["conversationId"] == conversation_id
    assert "用户：番茄炒蛋怎么做" in prompts[-1]


async def test_sync_local_conversations_is_idempotent(client):
    """登录后同步本地记录：重复上传不产生重复会话和重复消息。"""
    logged = await login(client, "13800000016")
    headers = auth_headers(logged["token"])
    payload = {
        "conversations": [
            {
                "clientConversationId": "local_conv_1",
                "contextType": "home",
                "updatedAt": "2026-11-25T10:00:00+00:00",
                "messages": [
                    {
                        "clientMessageId": "local_m1",
                        "role": "user",
                        "content": "番茄炒蛋怎么做",
                        "createdAt": "2026-11-25T09:59:00+00:00",
                    },
                    {
                        "clientMessageId": "local_m2",
                        "role": "assistant",
                        "content": "先炒鸡蛋，再炒番茄。",
                        "createdAt": "2026-11-25T10:00:00+00:00",
                    },
                ],
            }
        ]
    }
    first = await client.post(
        f"{API}/ai/conversations/sync", json=payload, headers=headers
    )
    assert first.status_code == 200, first.text
    first_data = data_of(first)
    assert first_data["insertedMessages"] == 2
    conversation_id = first_data["conversations"][0]["conversationId"]
    assert first_data["conversations"][0]["clientConversationId"] == "local_conv_1"

    # 原样重复同步：全部按客户端消息编号跳过。
    again = await client.post(
        f"{API}/ai/conversations/sync", json=payload, headers=headers
    )
    assert again.status_code == 200, again.text
    assert data_of(again)["insertedMessages"] == 0
    assert data_of(again)["conversations"][0]["conversationId"] == conversation_id

    # 本地新增一条消息：只补这一条。
    payload["conversations"][0]["messages"].append(
        {
            "clientMessageId": "local_m3",
            "role": "user",
            "content": "那换成鸡肉呢",
            "createdAt": "2026-11-25T10:05:00+00:00",
        }
    )
    third = await client.post(
        f"{API}/ai/conversations/sync", json=payload, headers=headers
    )
    assert third.status_code == 200, third.text
    assert data_of(third)["insertedMessages"] == 1

    async with app.state.test_session_factory() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(AIMessage)
            .where(AIMessage.conversation_id == conversation_id)
        )
        assert count == 3

    # 未登录不能同步：本地记录必须归属到明确账号。
    anonymous = await client.post(f"{API}/ai/conversations/sync", json=payload)
    assert anonymous.status_code == 401


async def test_cleanup_removes_expired_conversations_and_logs(client):
    """清理任务：会话 30 天、调用日志 180 天，最近数据不受影响。"""
    async with app.state.test_session_factory() as db:
        old_time = now_utc() - timedelta(days=31)
        recent_time = now_utc()
        # 两段会话：一段过期、一段仍然活跃。
        for conversation_id, moment in [
            ("conv_cleanup_old", old_time),
            ("conv_cleanup_new", recent_time),
        ]:
            db.add(
                AIConversation(
                    id=conversation_id,
                    subject_ref="user:cleanup_user",
                    user_id=None,
                    context_type="home",
                    title="清理测试",
                    summary=None,
                    summary_message_count=0,
                    message_count=1,
                    last_active_at=moment,
                    created_at=moment,
                    updated_at=moment,
                )
            )
            db.add(
                AIMessage(
                    id=f"aim_{conversation_id}",
                    conversation_id=conversation_id,
                    user_id=None,
                    client_message_id=f"cm_{conversation_id}",
                    role="user",
                    content="测试消息",
                    token_estimate=8,
                    created_at=moment,
                )
            )
        # 两条调用日志：一条超过 180 天，一条是最近的。
        for log_id, moment in [
            ("ail_cleanup_old", now_utc() - timedelta(days=181)),
            ("ail_cleanup_new", recent_time),
        ]:
            db.add(
                AICallLog(
                    id=log_id,
                    request_id=None,
                    subject_ref="guest:cleanup",
                    context_type="home",
                    provider_id=None,
                    provider_name="测试模型",
                    model="test-model",
                    status="success",
                    latency_ms=10,
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                    error_code=None,
                    error_message=None,
                    created_at=moment,
                )
            )
            db.add(
                AICallTrace(
                    id=f"trace_{log_id}",
                    call_log_id=log_id,
                    request_id=None,
                    seq=1,
                    step="model_request",
                    title="发起请求",
                    status="info",
                    detail="测试",
                    duration_ms=10,
                    created_at=moment,
                )
            )
            db.add(
                AICallScore(
                    id=f"score_{log_id}",
                    call_log_id=log_id,
                    score=4,
                    comment=None,
                    scorer_name="测试管理员",
                    source="manual",
                    langfuse_synced=False,
                    created_at=moment,
                )
            )
        await db.commit()

        deleted_conversations = await purge_expired_conversations(db)
        assert deleted_conversations == 1
        log_counts = await purge_expired_call_logs(db)
        assert log_counts == {"callLogs": 1, "callTraces": 1, "callScores": 1}

        # 孤儿明细：汇总日志可能被手工删除，只剩超过保留期的过程明细。
        db.add(
            AICallTrace(
                id="trace_orphan",
                call_log_id="ail_missing",
                request_id=None,
                seq=1,
                step="model_request",
                title="孤儿明细",
                status="info",
                detail="测试",
                duration_ms=10,
                created_at=now_utc() - timedelta(days=181),
            )
        )
        await db.commit()
        # 再跑一次：没有过期汇总日志时，也要按明细自己的时间清理孤儿明细。
        assert await purge_expired_call_logs(db) == {
            "callLogs": 0,
            "callTraces": 1,
            "callScores": 0,
        }

        # 孤儿会话：所属用户已经不存在，每天兜底清理一次。
        db.add(
            AIConversation(
                id="conv_orphan",
                subject_ref="user:ghost",
                user_id="u_ghost",
                context_type="home",
                title="孤儿会话",
                summary=None,
                summary_message_count=0,
                message_count=0,
                last_active_at=recent_time,
                created_at=recent_time,
                updated_at=recent_time,
            )
        )
        await db.commit()
        assert await purge_orphan_conversations(db) == 1
        assert await db.get(AIConversation, "conv_orphan") is None

        assert await db.get(AIConversation, "conv_cleanup_old") is None
        assert await db.get(AIConversation, "conv_cleanup_new") is not None
        old_messages = await db.scalar(
            select(func.count())
            .select_from(AIMessage)
            .where(AIMessage.conversation_id == "conv_cleanup_old")
        )
        assert old_messages == 0
        assert await db.get(AICallLog, "ail_cleanup_old") is None
        assert await db.get(AICallLog, "ail_cleanup_new") is not None
        assert await db.get(AICallTrace, "trace_ail_cleanup_old") is None
        # 评分跟随日志一起删除；最近那条日志的评分保留。
        assert await db.get(AICallScore, "score_ail_cleanup_old") is None
        assert await db.get(AICallScore, "score_ail_cleanup_new") is not None


async def test_delete_user_ai_data_removes_conversations_but_keeps_logs(client):
    """删除账号时只删对话，调用日志按 180 天自然到期。"""
    logged = await login(client, "13800000017")
    user_id = logged["profile"]["accountId"]
    await _seed_conversation(user_id, "conv_user_delete", message_count=2)

    async with app.state.test_session_factory() as db:
        db.add(
            AICallLog(
                id="ail_user_delete",
                request_id=None,
                subject_ref=f"user:{user_id}",
                context_type="home",
                provider_id=None,
                provider_name="测试模型",
                model="test-model",
                status="success",
                latency_ms=10,
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                error_code=None,
                error_message=None,
                created_at=now_utc(),
            )
        )
        await db.commit()

        removed = await delete_user_ai_data(db, user_id)
        assert removed == {"conversations": 1, "messages": 2}
        assert await db.get(AIConversation, "conv_user_delete") is None
        # 日志不跟着账号删除，保留到 180 天清理任务处理。
        assert await db.get(AICallLog, "ail_user_delete") is not None
