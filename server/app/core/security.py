"""与安全相关的纯函数：手机号加密/检索、验证码摘要、会话令牌。"""

import base64
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from cryptography.fernet import Fernet

from app.core.config import settings

# Argon2id 是 Argon2 的推荐变体：同时抵抗侧信道攻击和图形处理器暴力破解。
# 参数使用 argon2-cffi 的默认值，公司项目中通常按机器性能调优后写入配置。
_password_hasher = PasswordHasher()


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_phone(phone: str) -> str:
    return _fernet().encrypt(phone.encode("utf-8")).decode("ascii")


def decrypt_phone(token: str) -> str:
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")


def phone_lookup_key(phone: str) -> str:
    """不可逆索引，用于按手机号查找账号，不暴露明文。"""
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        f"phone:{phone}".encode(),
        hashlib.sha256,
    ).hexdigest()


def code_digest(challenge_id: str, code: str) -> str:
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        f"code:{challenge_id}:{code}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _token_fernet() -> Fernet:
    """会话令牌专用加密器。

    为什么不直接复用手机号加密器：不同用途使用不同密钥派生上下文，
    即使某一处密钥泄露，也不能拿同一份密文去解另一类数据。
    """
    digest = hashlib.sha256(
        f"{settings.secret_key}:session-token".encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def issue_session_token(session_id: str, prefix: str = "") -> tuple[str, str]:
    """生成加密后的会话令牌。

    Args:
        session_id: 数据库会话编号，例如 s_ab12cd34。
        prefix: 可选前缀，管理员令牌使用 adm_，便于日志区分。
    Returns:
        (返回给客户端的令牌, 用于计算摘要的明文载荷)。
    Why:
        需求要求后端返回加密后的令牌。客户端拿到的是不可读密文，
        服务端解密后得到“会话编号 + 随机串”，再与数据库中的摘要比对。
        这样既满足加密要求，又保留随机会话的不可预测性和可撤销性。
    """
    payload = f"{session_id}:{secrets.token_urlsafe(32)}"
    encrypted = _token_fernet().encrypt(payload.encode("utf-8")).decode("ascii")
    return f"{prefix}{encrypted}", payload


def read_session_token(token: str, prefix: str = "") -> tuple[str, str] | None:
    """解密客户端令牌，返回 (会话编号, 明文载荷)。

    解密失败、前缀不匹配或格式不合法一律返回 None，由调用方按未登录处理。
    不把异常抛给接口层，避免把加密库的内部错误暴露给客户端。
    """
    if not token:
        return None
    if prefix:
        if not token.startswith(prefix):
            return None
        token = token[len(prefix):]
    try:
        payload = _token_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except Exception:
        return None
    if ":" not in payload:
        return None
    session_id, secret = payload.split(":", 1)
    if not session_id or not secret:
        return None
    return session_id, payload


def _ai_secret_fernet() -> Fernet:
    """AI 模型密钥专用加密器。

    为什么不复用手机号或会话令牌的加密器：不同用途用不同派生上下文，
    某一类密文泄露时无法顺手解开另一类数据。
    """
    digest = hashlib.sha256(
        f"{settings.secret_key}:ai-provider-key".encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plain: str) -> str:
    """把需要服务端还原的第三方密钥加密后保存。

    Args:
        plain: 例如模型服务的 API Key。
    Returns:
        Fernet 密文，可直接写入数据库文本字段。
    Why:
        与密码不同，调用模型时必须拿到明文，所以不能只存哈希。
        Fernet 同时提供加密与完整性校验，密钥由 SECRET_KEY 派生，
        数据库被拖走时攻击者仍然无法解开。
    """
    return _ai_secret_fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    """还原被 encrypt_secret 加密的内容；密钥不匹配时抛异常，由调用方决定兜底。"""
    return _ai_secret_fernet().decrypt(token.encode("ascii")).decode("utf-8")


def mask_secret(plain: str) -> str:
    """把密钥变成可展示的掩码，例如 sk-abcd****wxyz。

    后台列表、详情、审计日志都只能出现掩码。
    保留少量首尾字符是为了让运营确认“填的是哪一把钥匙”，
    中间全部隐藏，避免肩窥或截图泄露完整密钥。
    """
    if len(plain) <= 8:
        return "****"
    return f"{plain[:4]}****{plain[-4:]}"


def token_digest(payload: str) -> str:
    """明文载荷的摘要，数据库只保存它，不保存可直接使用的令牌。"""
    return hashlib.sha256(f"token:{payload}".encode()).hexdigest()


def hash_password(password: str) -> str:
    """把明文密码转换成 Argon2id 哈希。

    Args:
        password: 用户输入的明文密码，只在内存中存在。
    Returns:
        可直接写入数据库的哈希字符串，包含算法、参数、盐和摘要。
    Why:
        密码必须可验证但不可还原。哈希是单向的，数据库泄露也拿不到明文。
    """
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """校验明文密码与数据库中的哈希是否匹配。

    Args:
        password_hash: 数据库中保存的 Argon2id 哈希。
        password: 用户本次输入的明文密码。
    Returns:
        匹配返回 True，不匹配或哈希格式损坏返回 False。
    Why:
        登录时不比较明文，而是让算法用相同参数重新计算并做恒定时间比较。
    """
    try:
        return _password_hasher.verify(password_hash, password)
    except Argon2Error:
        # 哈希被截断、算法参数不合法等都按“密码不正确”处理，避免泄露内部细节。
        return False


def admin_token_digest(payload: str) -> str:
    """管理员令牌载荷的摘要，数据库泄露也无法直接使用令牌。"""
    return hashlib.sha256(f"admin-token:{payload}".encode()).hexdigest()


def mask_phone(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else "***"


def random_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def new_id(prefix: str) -> str:
    """稳定前缀 + 随机片段，不依赖客户端或当前时间。"""
    return f"{prefix}_{secrets.token_hex(8)}"
