from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user, guest_subject
from app.core.responses import ok
from app.db.models import User
from app.db.session import get_db
from app.schemas import AIChatRequest
from app.services.ai_service import chat, chat_stream

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/chat")
async def ai_chat(
    body: AIChatRequest,
    request: Request,
    viewer: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
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
