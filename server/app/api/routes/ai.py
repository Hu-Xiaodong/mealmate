from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_user, guest_subject
from app.core.responses import ok
from app.db.models import User
from app.db.session import get_db
from app.schemas import AIChatRequest, AISyncRequest
from app.services.ai_history_service import sync_conversations
from app.services.ai_service import chat, chat_stream

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/chat")
async def ai_chat(
    body: AIChatRequest,
    request: Request,
    viewer: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """普通问答。

    请求可以带 conversationId 复用同一段会话；
    服务端会自己保存历史，客户端不需要每次把全部对话都传上来。
    """
    subject = f"user:{viewer.id}" if viewer else guest_subject(request)
    return ok(await chat(db, viewer, subject, body))


@router.post("/chat/stream")
async def ai_chat_stream(
    body: AIChatRequest,
    request: Request,
    viewer: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """流式问答，按 SSE 逐段返回文字。

    为什么单独开一个接口而不是给 /chat 加参数：
    普通接口返回统一 JSON 信封（code/data），流式接口返回的是一串事件，
    两者的响应格式和客户端解析方式完全不同。分开后旧客户端不受影响，
    新客户端可以按能力选择用哪一个。
    """
    subject = f"user:{viewer.id}" if viewer else guest_subject(request)
    generator = await chat_stream(db, viewer, subject, body)
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            # 关闭各类代理的缓冲，否则文字会被攒成一大块才发给 App。
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/conversations/sync")
async def sync_local_conversations(
    body: AISyncRequest,
    viewer: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """把手机本地的 AI 对话记录合并到云端。

    为什么必须登录：
    本地记录属于某个人，云端必须知道“记到谁名下”；
    游客没有稳定身份，无法保证跨设备找回，也不应该占用服务端长期存储。

    为什么由客户端主动上传，而不是服务端去拉：
    本地记录在手机上，服务端没有访问权限；
    客户端只在登录成功时调用一次，上传最近保留期内的会话即可。

    幂等性：
    同一段本地会话重复上传时，服务端按“用户 + 本地会话编号”找到已有会话，
    再按“客户端消息编号”跳过已经写过的消息，不会产生重复记录。
    """
    return ok(
        await sync_conversations(db, viewer, body),
        "本地对话已合并到云端",
    )
