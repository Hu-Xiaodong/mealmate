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

    # 普通用户会话有效期，单位天。产品要求“60 天免登录”，
    # 即在 60 天内重复打开 App 不需要重新输入验证码；
    # 管理员会话单独用分钟级配置，避免高权限凭证长期有效。
    session_ttl_days: int = 60
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
    # 管理员会话有效期，单位分钟。产品要求 1 天（1440 分钟）；
    # 管理员权限高，虽然比普通用户的 60 天短很多，但仍要保留可主动撤销能力。
    admin_session_ttl_minutes: int = 1440
    # 登录失败统计窗口，单位分钟。
    admin_login_window_minutes: int = 10
    # 同一用户名 + 同一来源地址在窗口内允许的失败次数。
    admin_login_max_attempts: int = 5
    # 达到失败次数后的锁定时长，单位分钟。
    admin_lock_minutes: int = 15
    # 首次启动创建超级管理员。密码只从环境变量读取，代码中不写默认密码。
    admin_initial_username: str = "admin"
    admin_initial_password: str = ""

    # 模型供应商（地址、密钥、模型名、优先级）改由管理后台维护，见 ai_providers 表。
    # 这里只保留所有环境共用的配额，避免“配置分散在环境变量和数据库两处”。
    guest_ai_daily_limit: int = 5
    user_ai_daily_limit: int = 20
    # 是否启用每日问答次数限制。
    # 设为 false 时仍然记录使用次数（便于统计和以后恢复），但不再拒绝请求；
    # 用于演示、联调或模型额度充足时临时放开，不需要改代码。
    ai_daily_limit_enabled: bool = True

    # ---- AI 对话历史 ----
    # 每次请求只把最近多少条消息放进提示词。
    # 8 条约等于 4 轮问答，足够理解“那换成鸡肉呢”这类追问；
    # 再多对当前问题帮助有限，反而增加 token 费用和首字延迟。
    ai_history_window_messages: int = 8
    # 历史 token 达到模型上下文窗口的多少比例时触发压缩。
    # 0.6 给系统提示词、菜谱目录和本次回答留出余量；
    # 等到接近 100% 再压缩，压缩请求本身就可能先超限。
    ai_history_compress_ratio: float = 0.6
    # 会话空闲多久后自动开始新会话，单位分钟。
    ai_conversation_idle_minutes: int = 30
    # Redis 中会话快照的存活时间（秒），每次有新消息都会重新计时（滑动过期）。
    ai_history_redis_ttl_seconds: int = 1800
    # 登录用户会话在数据库中保留多少天。超期由每日清理命令物理删除。
    ai_conversation_retention_days: int = 30
    # AI 调用日志保留多少天。日志是排障与成本核算依据，要求保留更久。
    ai_call_log_retention_days: int = 180

    # ---- Langfuse（大模型可观测平台，可选接入）----
    # Langfuse 是一个开源的“大模型调用观测”服务：记录调用链、Token、成本、
    # 提示词版本和人工评分。本项目只把它当后端服务使用：
    # 后端通过它的开放接口写入数据、读取指标，管理后台用自己的页面展示，
    # 不嵌入 Langfuse 的网页界面，避免前端被第三方界面绑定。
    #
    # 为什么不直接使用 Langfuse 的官方 SDK：
    # 1. 官方 SDK 会额外引入 OpenTelemetry 等依赖，而本项目只需要几个固定接口；
    # 2. 直接用 HTTP 接口更容易解释每一步发了什么、收到了什么，
    #    也方便在测试里用假的 HTTP 响应验证，不依赖外网。
    #
    # 三个值都为空时自动关闭上报，功能照常运行：
    # 管理后台的观测页会显示“未配置”，日志以本地 ai_call_logs 为准。
    langfuse_base_url: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    # 调用 Langfuse 接口的超时时间（秒）。观测是旁路能力，
    # 绝对不能因为观测服务变慢而拖住用户问答，所以超时要短。
    langfuse_timeout_seconds: float = 3.0
    # 运行时提示词缓存时间（秒）。每轮问答都去 Langfuse 拉提示词会多一次网络请求，
    # 缓存后既能及时拿到新版本，又不会给每次问答增加延迟。
    langfuse_prompt_cache_seconds: int = 300

    @property
    def langfuse_configured(self) -> bool:
        """地址和两个密钥都填了才算配置完成。"""
        return bool(
            self.langfuse_base_url.strip()
            and self.langfuse_public_key.strip()
            and self.langfuse_secret_key.strip()
        )

    rank_cache_seconds: int = 10

    # ---- 地图服务（腾讯位置服务 WebService API）----
    # 只需要在服务端配置一个 Key，Flutter App、小程序、H5 都通过后端代理调用。
    # 为什么不把 Key 放到客户端：
    # 1. 客户端的 Key 会被反编译或抓包拿到，容易被盗刷额度；
    # 2. 多端各配一个 Key 增加维护成本；
    # 3. 后端可以统一做缓存、限流和错误兜底。
    # 为什么只接腾讯一家而不做“双地图”：
    # 两家服务商的请求参数、响应字段、错误码、地点编号都不同，
    # 同时接入等于所有地图逻辑写两遍、测试两遍，个人项目没有收益；
    # 后端代理已经隔离了供应商，将来真要换，只改服务层即可，客户端无感。
    tencent_map_key: str = ""
    # 腾讯地图的 Secret Key（简称 SK），只在控制台开启了“签名校验”时才需要。
    # 为什么需要两个密钥：Key 用来标识“是谁在调用”，SK 用来证明“请求确实由密钥持有者发出”。
    # 开启签名校验后，请求必须附带用 SK 计算的 sig 参数，否则腾讯会返回 111 签名验证失败。
    # SK 的权限比 Key 更高，绝对不能放到客户端，也不能提交到代码仓库。
    tencent_map_secret_key: str = ""
    # 调用腾讯地图接口的超时时间，单位秒。地图不可用时不能拖垮整个发布流程。
    map_timeout_seconds: float = 6.0

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
