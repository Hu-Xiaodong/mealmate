"""逻辑数据模型，对应 PRD 4.4.1。

ID 一律使用稳定前缀 + 随机片段，不依赖客户端时间。
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    phone_encrypted: Mapped[str] = mapped_column(Text)
    phone_lookup_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(40))
    avatar_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VerificationChallenge(Base):
    __tablename__ = "verification_challenges"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    phone_encrypted: Mapped[str] = mapped_column(Text)
    phone_lookup_key: Mapped[str] = mapped_column(String(64), index=True)
    purpose: Mapped[str] = mapped_column(String(20), default="login")
    code_digest: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AdminUser(Base):
    """管理后台账号。

    为什么不复用 users 表：普通用户注册无门槛、数量大、令牌有效期长；
    管理员数量少但权限极高。独立表可以把两套身份体系彻底隔开，
    避免普通用户端的任何越权漏洞直接影响后台。
    """

    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    # 登录名，唯一索引保证不会出现两个同名管理员。
    username: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    # 只保存 Argon2id 哈希，永远不保存明文，也无法反向还原。
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(40))
    # active 可登录；disabled 已停用，登录时直接拒绝。
    status: Mapped[str] = mapped_column(String(20), default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AdminRole(Base):
    """角色。权限不直接挂在账号上，而是先定义角色拥有哪些权限点。

    这样新增一个内容运营只需分配角色，不用逐条勾选权限，也不会漏配。
    """

    __tablename__ = "admin_roles"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(40))


class AdminUserRole(Base):
    """管理员与角色的多对多关联。

    一个管理员可以同时拥有多个角色，最终权限是这些角色权限点的并集。
    """

    __tablename__ = "admin_user_roles"
    __table_args__ = (UniqueConstraint("admin_id", "role_id", name="uq_admin_user_role"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    admin_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id"), index=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("admin_roles.id"), index=True)


class AdminRolePermission(Base):
    """角色与权限点的关联。

    权限点是一个最小操作单位的字符串，例如 post.review 表示审核饭帖。
    后端每个需要权限的接口都用 require_permission("post.review") 声明，
    未授权直接返回 403，前端隐藏按钮只作为体验优化。
    """

    __tablename__ = "admin_role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_code", name="uq_role_permission"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("admin_roles.id"), index=True)
    permission_code: Mapped[str] = mapped_column(String(60), index=True)


class AdminSession(Base):
    """管理员登录会话。

    与普通用户会话分开建表，原因有三点：
    1. 有效期更短，默认 1 天（1440 分钟）；
    2. 可以按管理员整体撤销；
    3. 令牌摘要独立存储，两套令牌不能互相冒用。
    """

    __tablename__ = "admin_sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    admin_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id"), index=True)
    # 数据库只保存 SHA-256 摘要，即使泄露也无法直接拿摘要当令牌使用。
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AdminLoginAttempt(Base):
    """管理员登录失败统计。

    需求是“同一用户名 + 同一来源地址 10 分钟内失败 5 次，锁定 15 分钟”。
    因此计数键是用户名与来源地址的组合，而不是只按用户名。
    这张表是方案文档 5.1 节的实现补充：如果不落库，服务重启后锁定状态会丢失。
    """

    __tablename__ = "admin_login_attempts"
    __table_args__ = (
        UniqueConstraint("username", "ip", name="uq_admin_login_attempt"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    username: Mapped[str] = mapped_column(String(40), index=True)
    ip: Mapped[str] = mapped_column(String(64))
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    # 本轮计数的开始时间，超过窗口后重新从 0 开始。
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AuditLog(Base):
    """审计日志：只追加，不修改，不删除。

    记录“谁在什么时间、从哪里、对什么对象、做了什么、为什么”。
    拒绝和下架必须填写原因，因此 reason 在业务层做强制校验。
    before_json 与 after_json 保存变更前后的关键字段快照，
    排查问题时不用去猜当时的数据长什么样。

    应用层不提供修改和删除接口；生产环境建议数据库账号也只授予插入权限。
    """

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(40), index=True)
    # 操作人名称快照。即使以后改名或删除账号，历史日志仍然可读。
    actor_name: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(60), index=True)
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str] = mapped_column(String(40), index=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 与接口响应头 X-Request-Id 一致，便于把一次操作和一条日志对上。
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class MealPost(Base):
    __tablename__ = "meal_posts"
    __table_args__ = (
        UniqueConstraint("author_id", "client_request_id", name="uq_post_author_request"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(24))
    review: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(20), index=True)
    image_asset_ids: Mapped[list[str]] = mapped_column(JSON)
    author_recipe: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    platform_recipe_id: Mapped[str | None] = mapped_column(
        ForeignKey("recipes.id"), nullable=True
    )
    takeaway_store: Mapped[str | None] = mapped_column(String(80), nullable=True)
    dine_in_address: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # 人均价格，单位元。允许为空，因为很多用户只记得“花了多少钱”而不想精确到分。
    # 使用整数而不是小数：餐饮人均极少精确到角，整数足够，也避免浮点误差。
    avg_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 口味标签，存 JSON 数组，例如 ["微辣", "重口下饭"]。
    # 为什么不建单独的标签关联表：标签是固定枚举、数量少、只用于展示和筛选，
    # 用 JSON 数组读写更简单；如果以后要按标签做热门统计，再拆表也不迟。
    taste_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    # 店铺坐标：与 coarse_lat/coarse_lng 区分开。
    # coarse_* 是发布者本人的粗略位置，用于“附近”推荐；
    # store_* 是餐厅的精确位置，只用于详情页地图与导航，不参与附近排序。
    store_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    store_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 地图服务的地点编号（当前为腾讯地点搜索返回的 id），便于以后重新拉取该店铺信息或去重。
    store_poi_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 发布者本人的粗略位置，用于“附近”推荐，只保留三位小数。
    coarse_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    coarse_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    coarse_area: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # 状态取值：draft 草稿、pending_review 待审核、published 已发布、
    # rejected 已拒绝、unpublished 已下架、deleted 作者已删除。
    status: Mapped[str] = mapped_column(String(20), default="pending_review", index=True)
    # 软删除时间。作者删除饭帖时只改状态并记录时间，不物理删除数据。
    # 这样做一是保留审计与统计口径，二是避免点赞、收藏等外键悬空。
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 审核记录：谁审的、什么时候审的、拒绝或下架的原因。
    # reviewed_by 指向管理员表，但不做级联删除，历史审核记录必须保留。
    reviewed_by: Mapped[str | None] = mapped_column(
        ForeignKey("admin_users.id"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    client_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(40))
    cover_url: Mapped[str] = mapped_column(String(255))
    total_minutes: Mapped[int] = mapped_column(Integer)
    tool_codes: Mapped[list[str]] = mapped_column(JSON)
    category_codes: Mapped[list[str]] = mapped_column(JSON)
    servings: Mapped[float] = mapped_column(Float, default=1)
    main_ingredients: Mapped[list[str]] = mapped_column(JSON)
    ingredients: Mapped[list[dict]] = mapped_column(JSON)
    steps: Mapped[list[str]] = mapped_column(JSON)
    preconditions: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content_origin: Mapped[str] = mapped_column(String(20), default="platform")
    validation_status: Mapped[str] = mapped_column(String(20), default="tested")
    status: Mapped[str] = mapped_column(String(20), default="published", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecipeCategory(Base):
    __tablename__ = "recipe_categories"
    __table_args__ = (UniqueConstraint("recipe_id", "code", name="uq_recipe_category"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id"), index=True)
    code: Mapped[str] = mapped_column(String(20), index=True)


class Like(Base):
    __tablename__ = "likes"
    __table_args__ = (UniqueConstraint("account_id", "post_id", name="uq_like_account_post"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    post_id: Mapped[str] = mapped_column(ForeignKey("meal_posts.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    risk_status: Mapped[str] = mapped_column(String(20), default="valid")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("account_id", "target_type", "target_id", name="uq_favorite_target"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str] = mapped_column(String(40))
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    mime: Mapped[str] = mapped_column(String(40))
    bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(255))
    thumb_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="ready")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIUsage(Base):
    __tablename__ = "ai_usage"
    __table_args__ = (UniqueConstraint("subject_ref", "usage_date", name="uq_ai_usage_subject"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    subject_ref: Mapped[str] = mapped_column(String(80), index=True)
    usage_date: Mapped[date] = mapped_column(Date, index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class AIProvider(Base):
    """大模型供应商配置。

    为什么把模型配置放进数据库，而不是只写在环境变量里：
    1. 产品要求运营可以在管理后台自行新增、停用、调整顺序，不需要改代码重启服务；
    2. 需要同时配置多个模型做自动分配，环境变量只能表达“一个模型”；
    3. 密钥需要加密保存、列表只显示掩码，这类操作必须经过后台权限与审计。

    为什么单独建表，不塞进一张通用“系统配置”键值表：
    模型配置有明确的结构（地址、模型名、超时、优先级、测试结果），
    单独建表后字段有类型约束、可以建唯一索引，查询和校验都比解析一大段 JSON 可靠。

    provider_type 当前只有 openai_compatible 一种：
    市面上绝大多数模型服务（DeepSeek、通义千问、Kimi、智谱、OpenAI、以及自建的 vLLM）
    都提供“OpenAI 兼容”的聊天接口，请求路径和字段基本一致。
    抽象成一种类型后，新增一家供应商通常只需要填地址、密钥、模型名，不用改代码。
    """

    __tablename__ = "ai_providers"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    # 后台展示用的名称，例如“DeepSeek 主力”“通义备用”。唯一，避免运营选错。
    name: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    provider_type: Mapped[str] = mapped_column(String(30), default="openai_compatible")
    # 接口根地址，例如 https://api.deepseek.com/v1。
    # 末尾补 /chat/completions 的逻辑集中在服务层，避免每家供应商各写一份。
    base_url: Mapped[str] = mapped_column(String(255))
    # 密钥只保存加密后的密文。Fernet 是对称加密：服务端能解密去调用模型，
    # 但数据库泄露时攻击者没有 SECRET_KEY 仍然解不开。
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    # 模型名，例如 deepseek-chat、qwen-plus。不同供应商的叫法不同，所以由运营填写。
    model: Mapped[str] = mapped_column(String(80))
    # 停用后不参与自动分配，但配置保留，方便随时恢复。
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 数字越小越先尝试。自动分配按优先级升序逐个调用，失败再换下一个。
    priority: Mapped[int] = mapped_column(Integer, default=100)
    # 单次调用超时时间，单位秒。模型服务变慢时不能一直占着用户请求。
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=20)
    # 限制模型最多输出多少 token（模型计费与长度单位），防止异常长回复拖慢响应。
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=800)
    # 最近一次“测试连接”的结果，便于运营在后台直接看到是否可用。
    last_test_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AICallLog(Base):
    """AI 调用日志：每次尝试调用模型都记一行。

    为什么必须落库而不是只写应用日志：
    1. 需要回答“今天 AI 失败了几次、是哪个模型、错误码是什么”，应用日志检索成本高；
    2. token 消耗是成本核算依据，必须能按供应商、模型聚合；
    3. 多模型自动分配时，一次用户提问可能尝试多次，只有逐次记录才能还原过程。

    为什么 provider_id 不做外键：供应商配置可能被删除，但历史调用记录必须保留。
    这里同时保存 provider_name 快照，删除配置后日志仍然可读，
    和审计日志保存操作人名称快照是同一个思路。
    """

    __tablename__ = "ai_call_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    # 与接口响应头 X-Request-Id 一致，便于把一次用户提问和多次模型尝试串起来。
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 调用者标识：登录用户是 user:xxx，游客是设备标识。不存手机号等个人信息。
    subject_ref: Mapped[str] = mapped_column(String(80), index=True)
    # 提问场景：home 首页、post 饭帖详情、recipe_list 菜谱列表，用于分析使用分布。
    context_type: Mapped[str] = mapped_column(String(20))
    provider_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider_name: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    # success 表示模型正常返回并通过了菜谱编号校验；failed 表示这次尝试失败。
    status: Mapped[str] = mapped_column(String(20), index=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    # token 是模型服务计费和限流的计量单位，供应商会在响应的 usage 字段返回。
    # 部分兼容接口不返回 usage，此时保持 0，不能因此判定调用失败。
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class TasteTag(Base):
    """口味标签字典表。

    为什么把标签从代码里的写死枚举搬到数据库：
    1. 标签属于运营数据，产品想增减一个口味时不应该改代码再发版；
    2. 前端展示哪些标签、按什么顺序展示，都以这张表为准，避免两端各写一份慢慢对不上；
    3. 后台以后要做“标签管理”时，直接改这张表即可，接口不需要变。

    为什么用 name 直接做主键而不额外造一个编号：
    标签本身很短、天然唯一、就是业务主键，饭帖里保存的也是标签文字（JSON 数组），
    用文字做主键可以让“饭帖里的标签”和“字典里的标签”直接对应，查询时少一次关联。
    代价是以后改标签文字要同步改历史饭帖，但口味标签基本不会改名，可以接受。

    对比方案：
    - 代码里的 Literal 枚举：简单，但每次调整都要发版，运营无法自助；
    - 枚举字典表（本方案）：可运营、可排序、可停用，成本很低，是公司里最常见的做法；
    - 独立标签表 + 饭帖标签关联表（多对多）：适合标签数量成百上千、需要按标签统计热度的场景，
      当前只有不到二十个固定标签，用 JSON 数组存饭帖标签已经够用，没必要提前拆表。
    """

    __tablename__ = "taste_tags"

    # 标签文字，例如“香辣”。主键保证不会出现两条同名标签。
    name: Mapped[str] = mapped_column(String(20), primary_key=True)
    # 展示顺序，数字越小越靠前。前端按这个字段升序排列。
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # 是否启用。停用后不再下发给前端，也不能被新饭帖选用。
    # 为什么用“停用”而不是直接删除：历史饭帖里可能还在引用这个标签，
    # 直接删行会让历史数据变成“查不到的标签”，排查问题时很麻烦。
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnalyticsEvent(Base):
    """客户端埋点事件。

    为什么单独建表，而不是塞进日志文件：
    1. 看板要按事件名、日期、平台做聚合，关系型表可以直接 group by；
    2. event_id 作为主键天然去重，客户端重试不会把曝光量算两次；
    3. 埋点属于分析数据，和业务表分开后可以单独设置保留期限与清理任务。

    为什么 account_id 允许为空：游客也能浏览和打开详情，
    匿名事件同样有价值；登录后由后端从令牌解析账号并回填，前端不传。
    """

    __tablename__ = "analytics_events"

    # 客户端生成的事件唯一编号。用它做主键，重复上报会触发唯一约束而被跳过。
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 登录用户编号；游客为空。不做级联删除，历史统计仍需保留。
    account_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    event_name: Mapped[str] = mapped_column(String(40), index=True)
    page_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(20), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 一次应用启动内稳定的随机编号，用于把同一次访问的事件串起来。
    session_ref: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 请求类事件可以带上接口返回的 requestId，便于和错误日志对齐。
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 事件专有属性。只存分析需要的字段，禁止写入手机号、令牌、原文。
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    # 事件实际发生时间（客户端时钟）与服务端接收时间，两者都保留以便排查时区问题。
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserLocation(Base):
    """用户最近一次定位结果，每个账号只保留一条。

    用途：用户没有开启手机定位时，退而使用上一次成功定位的位置，
    保证“外卖 / 到店”选店铺时仍然有一个可用的地图中心点。

    为什么只保留一条“最新”记录，而不是保存定位历史流水：
    - 业务上只需要“最近一次在哪”，旧位置没有使用场景；
    - 一条记录用主键直接覆盖更新，读写都是常数级，不需要清理历史数据；
    - 定位属于敏感个人信息，少存即少风险，能不留历史就不留。

    为什么 account_id 直接做主键：一个账号只能有一条最新定位，
    主键天然保证唯一，插入时不需要先查再判断，直接覆盖即可。
    """

    __tablename__ = "user_locations"

    account_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    # 纬度、经度。使用双精度浮点（Double Precision）保存，
    # 与饭帖里的坐标字段保持一致，避免不同表精度不同导致对不上。
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    # 逆地址解析出的区域名称，例如“上海市徐汇区”。可能为空（定位服务不返回或解析失败）。
    area: Mapped[str | None] = mapped_column(String(80), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
