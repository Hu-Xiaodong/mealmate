from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user, guest_subject
from app.core.responses import ok
from app.db.models import User
from app.db.session import get_db
from app.schemas import AIChatRequest
from app.services.ai_service import chat

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
