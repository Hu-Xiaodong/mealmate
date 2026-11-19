"""应用配置。

所有可变参数集中在此，生产环境通过环境变量覆盖 `.env`。
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MealMate API"
    app_env: Literal["dev", "test", "prod"] = "dev"
    api_prefix: str = "/api/v1"

    database_url: str = "sqlite+aiosqlite:///./mealmate_dev.db"
    redis_url: str = ""
    secret_key: str = "dev-only-change-me-in-production"

    session_ttl_days: int = 30
    sms_code_ttl_seconds: int = 300
    sms_resend_seconds: int = 60
    sms_max_attempts: int = 5
    allow_dev_auth_code: bool = True
    dev_auth_code: str = "123456"

    auto_publish_posts: bool = True
    seed_demo_data: bool = True
    public_base_url: str = "http://127.0.0.1:8000"
    media_backend: Literal["local", "s3"] = "local"
    media_root: Path = BASE_DIR / "media"
    # 管理后台运行在 5174 端口，与面向用户的 5173 端口分开。
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174"
    )

    # ---- 管理后台 ----
    # 管理员会话有效期，单位分钟。高权限账号使用短会话，泄露后的窗口更小。
    admin_session_ttl_minutes: int = 120
    # 登录失败统计窗口，单位分钟。
    admin_login_window_minutes: int = 10
    # 同一用户名 + 同一来源地址在窗口内允许的失败次数。
    admin_login_max_attempts: int = 5
    # 达到失败次数后的锁定时长，单位分钟。
    admin_lock_minutes: int = 15
    # 首次启动创建超级管理员。密码只从环境变量读取，代码中不写默认密码。
    admin_initial_username: str = "admin"
    admin_initial_password: str = ""

    ai_provider: str = "mock"
    ai_api_base: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    guest_ai_daily_limit: int = 5
    user_ai_daily_limit: int = 20

    rank_cache_seconds: int = 10

    @model_validator(mode="after")
    def _guard_production(self):
        # 固定验证码只能存在于开发/测试环境，生产启动即拒绝。
        if self.app_env == "prod" and self.allow_dev_auth_code:
            raise ValueError("生产环境禁止启用固定演示验证码 ALLOW_DEV_AUTH_CODE")
        if self.app_env == "prod" and self.seed_demo_data:
            raise ValueError("生产环境禁止写入演示种子数据 SEED_DEMO_DATA")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
