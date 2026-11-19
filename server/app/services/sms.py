"""短信发送适配器。

开发/测试环境只打印验证码；生产环境必须接入真实供应商后实现 send()。
"""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_login_code(phone: str, code: str) -> None:
    if settings.app_env == "prod":
        raise RuntimeError("生产短信供应商尚未配置，禁止回退到演示验证码")
    logger.info("演示短信验证码 phone=%s code=%s", phone, code)
