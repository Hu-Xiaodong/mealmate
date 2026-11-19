import hashlib

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import User
from app.db.session import get_db
from app.services.auth_service import resolve_session


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AppError("SESSION_INVALID", "登录状态无效，请重新登录", status_code=401)
    return token.strip()


async def get_optional_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User | None:
    token = _bearer_token(request)
    if not token:
        return None
    user = await resolve_session(db, token)
    if user is None:
        raise AppError("SESSION_EXPIRED", "登录已失效，请重新登录", status_code=401)
    return user


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    user = await get_optional_user(request, db)
    if user is None:
        raise AppError("UNAUTHENTICATED", "请先登录后再继续", status_code=401)
    return user


def guest_subject(request: Request) -> str:
    device = (request.headers.get("x-device-id") or "").strip()
    if device:
        return f"guest:{device[:64]}"
    ip = request.client.host if request.client else "unknown"
    return f"guest:ip:{hashlib.sha256(ip.encode()).hexdigest()[:16]}"
