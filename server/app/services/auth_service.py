from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import (
    code_digest,
    decrypt_phone,
    encrypt_phone,
    mask_phone,
    new_id,
    new_token,
    phone_lookup_key,
    random_code,
    token_digest,
)
from app.db.models import Session, User, VerificationChallenge
from app.services.sms import send_login_code
from app.utils.time import as_utc, now_utc


class AuthResult:
    def __init__(self, user: User, token: str, expires_at, is_new: bool):
        self.user = user
        self.token = token
        self.expires_at = expires_at
        self.is_new = is_new


async def issue_login_code(
    db: AsyncSession, phone: str, purpose: str
) -> tuple[VerificationChallenge, str | None]:
    now = now_utc()
    latest = await db.scalar(
        select(VerificationChallenge)
        .where(
            VerificationChallenge.phone_lookup_key == phone_lookup_key(phone),
            VerificationChallenge.purpose == purpose,
        )
        .order_by(VerificationChallenge.created_at.desc())
        .limit(1)
    )
    if latest and latest.used_at is None:
        created = as_utc(latest.created_at)
        retry_at = created + timedelta(seconds=settings.sms_resend_seconds)
        if retry_at > now:
            raise AppError(
                "SMS_RATE_LIMITED",
                "请求过于频繁，请稍后再试",
                status_code=429,
                data={"retryAfter": int((retry_at - now).total_seconds())},
                headers={"Retry-After": str(int((retry_at - now).total_seconds()))},
            )

    # 同一手机号只保留最新一次有效挑战。
    stale = (
        await db.scalars(
            select(VerificationChallenge).where(
                VerificationChallenge.phone_lookup_key == phone_lookup_key(phone),
                VerificationChallenge.used_at.is_(None),
            )
        )
    ).all()
    for challenge in stale:
        challenge.used_at = now

    code = settings.dev_auth_code if settings.allow_dev_auth_code else random_code()
    challenge = VerificationChallenge(
        id=new_id("vc"),
        phone_encrypted=encrypt_phone(phone),
        phone_lookup_key=phone_lookup_key(phone),
        purpose=purpose,
        code_digest=code_digest("pending", code),
        expires_at=now + timedelta(seconds=settings.sms_code_ttl_seconds),
    )
    challenge.code_digest = code_digest(challenge.id, code)
    db.add(challenge)
    await db.commit()

    send_login_code(phone, code)
    return challenge, code if settings.allow_dev_auth_code else None


async def verify_login(
    db: AsyncSession,
    *,
    challenge_id: str,
    code: str,
    agreement_accepted: bool,
    device_ref: str | None,
) -> AuthResult:
    if not agreement_accepted:
        raise AppError("AGREEMENT_REQUIRED", "请先阅读并同意用户协议与隐私说明")

    now = now_utc()
    challenge = await db.get(VerificationChallenge, challenge_id)
    if challenge is None:
        raise AppError("CHALLENGE_NOT_FOUND", "验证码不存在，请重新获取", status_code=400)
    if challenge.used_at is not None:
        raise AppError("CODE_USED", "验证码已使用，请重新获取")
    if challenge.failed_attempts >= settings.sms_max_attempts:
        raise AppError("CODE_LOCKED", "验证失败次数过多，请重新获取验证码")
    if as_utc(challenge.expires_at) < now:
        raise AppError("CODE_EXPIRED", "验证码已过期，请重新获取")

    if code_digest(challenge.id, code) != challenge.code_digest:
        challenge.failed_attempts += 1
        await db.commit()
        remaining = settings.sms_max_attempts - challenge.failed_attempts
        raise AppError(
            "CODE_INVALID",
            "验证码不正确",
            data={"remainingAttempts": max(remaining, 0)},
        )

    challenge.used_at = now
    phone = decrypt_phone(challenge.phone_encrypted)
    lookup = challenge.phone_lookup_key
    user = await db.scalar(select(User).where(User.phone_lookup_key == lookup))
    is_new = user is None
    if user is None:
        user = User(
            id=new_id("u"),
            phone_encrypted=challenge.phone_encrypted,
            phone_lookup_key=lookup,
            nickname=f"饭友{phone[-4:]}",
            status="active",
        )
        db.add(user)
        await db.flush()

    token = new_token()
    expires_at = now + timedelta(days=settings.session_ttl_days)
    db.add(
        Session(
            id=new_id("s"),
            account_id=user.id,
            token_digest=token_digest(token),
            expires_at=expires_at,
            device_ref=device_ref,
        )
    )
    await db.commit()
    return AuthResult(user=user, token=token, expires_at=expires_at, is_new=is_new)


async def revoke_session(db: AsyncSession, token: str) -> None:
    session = await db.scalar(
        select(Session).where(Session.token_digest == token_digest(token))
    )
    if session and session.revoked_at is None:
        session.revoked_at = now_utc()
        await db.commit()


async def resolve_session(db: AsyncSession, token: str) -> User | None:
    session = await db.scalar(
        select(Session)
        .where(Session.token_digest == token_digest(token), Session.revoked_at.is_(None))
        .order_by(Session.created_at.desc())
        .limit(1)
    )
    if session is None or as_utc(session.expires_at) < now_utc():
        return None
    user = await db.get(User, session.account_id)
    if user is None or user.status != "active":
        return None
    return user


def profile_payload(user: User) -> dict[str, Any]:
    phone = decrypt_phone(user.phone_encrypted)
    return {
        "accountId": user.id,
        "nickname": user.nickname,
        "avatarUrl": user.avatar_url,
        "phoneMasked": mask_phone(phone),
        "status": user.status,
    }
