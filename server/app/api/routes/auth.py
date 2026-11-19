from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.serializers import iso
from app.core.config import settings
from app.core.errors import AppError
from app.core.responses import ok
from app.db.models import User
from app.db.session import get_db
from app.schemas import LoginRequest, SmsCodeRequest
from app.services.auth_service import (
    issue_login_code,
    profile_payload,
    revoke_session,
    verify_login,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/sms-codes")
async def send_sms_code(body: SmsCodeRequest, db: AsyncSession = Depends(get_db)):
    challenge, dev_code = await issue_login_code(db, body.phone, body.purpose)
    data = {
        "challengeId": challenge.id,
        "expiresIn": settings.sms_code_ttl_seconds,
        "retryAfter": settings.sms_resend_seconds,
        "purpose": challenge.purpose,
    }
    if dev_code is not None:
        # 仅开发/测试环境返回，生产由 Settings 守卫强制关闭。
        data["devCode"] = dev_code
    return ok(data, "验证码已发送")


@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await verify_login(
        db,
        challenge_id=body.challenge_id,
        code=body.code,
        agreement_accepted=body.agreement_accepted,
        device_ref=body.device_ref,
    )
    return ok(
        {
            "accountId": result.user.id,
            "token": result.token,
            "tokenType": "Bearer",
            "expiresAt": iso(result.expires_at),
            "isNewAccount": result.is_new,
            "profile": profile_payload(result.user),
        },
        "登录成功",
    )


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return ok(profile_payload(user))


@router.post("/logout")
async def logout(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    header = request.headers.get("authorization", "")
    token = header.partition(" ")[2].strip()
    if not token:
        raise AppError("SESSION_INVALID", "登录状态无效", status_code=401)
    await revoke_session(db, token)
    return ok({"revoked": True}, "已退出登录")
