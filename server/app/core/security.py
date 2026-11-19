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


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(f"token:{token}".encode()).hexdigest()


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


def admin_new_token() -> str:
    """生成管理员会话令牌。前缀便于日志和排查时区分普通用户令牌。"""
    return f"adm_{secrets.token_urlsafe(32)}"


def admin_token_digest(token: str) -> str:
    """管理员令牌只保存摘要，数据库泄露也无法直接使用令牌。"""
    return hashlib.sha256(f"admin-token:{token}".encode()).hexdigest()


def mask_phone(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else "***"


def random_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def new_id(prefix: str) -> str:
    """稳定前缀 + 随机片段，不依赖客户端或当前时间。"""
    return f"{prefix}_{secrets.token_hex(8)}"
