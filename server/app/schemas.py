"""请求体模型。响应由 serializer 输出 camelCase 字典。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SmsCodeRequest(CamelModel):
    phone: str = Field(pattern=r"^1\d{10}$")
    purpose: Literal["login"] = "login"
    agreement_version: str | None = Field(default=None, max_length=40)


class LoginRequest(CamelModel):
    challenge_id: str = Field(min_length=4, max_length=40)
    code: str = Field(pattern=r"^\d{6}$")
    agreement_accepted: bool
    device_ref: str | None = Field(default=None, max_length=120)


class AuthorRecipeInput(CamelModel):
    ingredients: list[str] = Field(min_length=1, max_length=20)
    steps: list[str] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def _clean(self):
        self.ingredients = [item.strip() for item in self.ingredients if item.strip()]
        self.steps = [item.strip() for item in self.steps if item.strip()]
        if not self.ingredients or not self.steps:
            raise ValueError("食材和步骤需要成对填写")
        return self


class LocationInput(CamelModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    area: str | None = Field(default=None, max_length=80)
    public_consent: bool = False


# 口味标签不再写成代码里的固定枚举：
# 标签是可运营的数据，改由数据库字典表 taste_tags 统一维护，
# 后端在写入时按数据库里“已启用”的标签做校验。
# 为什么请求体里仍然用字符串列表而不是直接信任客户端：
# 字符串只是“传输格式”，真正的合法性以数据库为准，避免客户端伪造不存在的标签。
# 自由输入同样不允许：用户只能从前端展示的字典里选，保证标签可筛选、可统计。
TasteTagText = str


class StoreLocationInput(CamelModel):
    """店铺坐标，来自地图选点。

    只保存经纬度和地图地点编号，不保存搜索关键词。
    经纬度保留 6 位小数（约 0.1 米），因为导航需要尽量精确的位置；
    与“公开大概位置”刻意降低精度不同，店铺位置本来就是公开信息。
    """

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    poi_id: str | None = Field(default=None, max_length=64)


def _normalize_posts_input(
    *,
    title: str,
    review: str,
    location: LocationInput | None,
    taste_tags: list[str],
    store_location: StoreLocationInput | None,
) -> tuple[str, str, LocationInput | None, list[str], StoreLocationInput | None]:
    """清理标题、评价、位置与标签，供发布和草稿两个入口复用。

    抽成函数的目的是避免“发布”和“存草稿”两套校验逻辑慢慢跑偏：
    以后新增字段时只需要改这一处，两个入口自动保持一致。
    """
    title = title.strip()
    review = review.strip()

    # 公开位置必须经过用户明确同意，并且只保留三位小数（约百米级）。
    if location is None or not location.public_consent:
        location = None
    else:
        location.lat = round(location.lat, 3)
        location.lng = round(location.lng, 3)

    # 标签去重但保留用户选择顺序；最多三个由字段的 max_length 限制。
    taste_tags = list(dict.fromkeys(taste_tags))

    if store_location is not None:
        store_location.lat = round(store_location.lat, 6)
        store_location.lng = round(store_location.lng, 6)
        if store_location.poi_id is not None:
            store_location.poi_id = store_location.poi_id.strip() or None
    return title, review, location, taste_tags, store_location


class CreatePostRequest(CamelModel):
    title: str = Field(min_length=1, max_length=24)
    review: str = Field(min_length=1, max_length=200)
    source: Literal["self", "takeaway", "dine_in"]
    image_asset_ids: list[str] = Field(min_length=1, max_length=9)
    author_recipe: AuthorRecipeInput | None = None
    takeaway_store: str | None = Field(default=None, max_length=80)
    dine_in_address: str | None = Field(default=None, max_length=160)
    location: LocationInput | None = None
    # 人均价格，单位元。上限 9999 是为了挡住误输入，例如把手机号填进来。
    avg_price: int | None = Field(default=None, ge=0, le=9999)
    taste_tags: list[TasteTagText] = Field(default_factory=list, max_length=3)
    store_location: StoreLocationInput | None = None

    @model_validator(mode="after")
    def _branch_validation(self):
        (
            self.title,
            self.review,
            self.location,
            self.taste_tags,
            self.store_location,
        ) = _normalize_posts_input(
            title=self.title,
            review=self.review,
            location=self.location,
            taste_tags=self.taste_tags,
            store_location=self.store_location,
        )
        if not self.title or not self.review:
            raise ValueError("菜名和评价不能为空")

        if self.source == "takeaway":
            if not (self.takeaway_store or "").strip():
                raise ValueError("外卖来源需要填写店家名称")
            self.dine_in_address = None
        elif self.source == "dine_in":
            if not (self.dine_in_address or "").strip():
                raise ValueError("到店来源需要填写店铺地址")
            self.takeaway_store = None
        else:
            self.takeaway_store = None
            self.dine_in_address = None
            # 自己做饭没有“店铺”，清掉避免脏数据。
            self.store_location = None
        return self


class DraftPostRequest(CamelModel):
    """草稿保存请求。

    草稿允许“什么都没填”：用户可能只是先选了几张图就退出。
    因此这里只做长度和格式校验，不强制要求菜名、评价、图片或来源。
    真正发布时仍会走 CreatePostRequest 的完整校验，草稿不会绕过审核规则。
    """

    title: str = Field(default="", max_length=24)
    review: str = Field(default="", max_length=200)
    source: Literal["self", "takeaway", "dine_in"] | None = None
    image_asset_ids: list[str] = Field(default_factory=list, max_length=9)
    author_recipe: AuthorRecipeInput | None = None
    takeaway_store: str | None = Field(default=None, max_length=80)
    dine_in_address: str | None = Field(default=None, max_length=160)
    location: LocationInput | None = None
    avg_price: int | None = Field(default=None, ge=0, le=9999)
    taste_tags: list[TasteTagText] = Field(default_factory=list, max_length=3)
    store_location: StoreLocationInput | None = None

    @model_validator(mode="after")
    def _clean_draft(self):
        (
            self.title,
            self.review,
            self.location,
            self.taste_tags,
            self.store_location,
        ) = _normalize_posts_input(
            title=self.title,
            review=self.review,
            location=self.location,
            taste_tags=self.taste_tags,
            store_location=self.store_location,
        )
        return self


class SaveLocationRequest(CamelModel):
    """保存“我最近一次定位”的请求体。

    只接收经纬度和可选的区域名称，不接收用户编号：
    用户编号从登录令牌里取，客户端无法替别人保存定位。
    """

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    area: str | None = Field(default=None, max_length=80)


class LikeRequest(CamelModel):
    liked: bool


class FavoriteRequest(CamelModel):
    target_type: Literal["post", "recipe"]
    target_id: str = Field(min_length=4, max_length=40)
    saved: bool


class AIConstraints(CamelModel):
    max_minutes: int | None = Field(default=None, ge=1, le=180)
    tools: list[str] = Field(default_factory=list, max_length=5)
    ingredients: list[str] = Field(default_factory=list, max_length=10)
    avoid: list[str] = Field(default_factory=list, max_length=10)


class AIChatRequest(CamelModel):
    context_type: Literal["home", "post", "recipe_list"] = "home"
    context_id: str | None = Field(default=None, max_length=40)
    message: str = Field(min_length=1, max_length=500)
    constraints: AIConstraints = Field(default_factory=AIConstraints)


class AIProviderCreateRequest(CamelModel):
    """后台新增一个模型供应商。

    这里只放“运营需要填写的字段”，不接收供应商编号与时间：
    编号由服务端生成，时间由数据库自动维护，客户端传了也不会被采用。
    """

    name: str = Field(min_length=1, max_length=40)
    # 目前只支持 OpenAI 兼容协议，写成 Literal 后，传其他值会直接返回 422。
    provider_type: Literal["openai_compatible"] = "openai_compatible"
    # 配置用途：chat 聊天补全、embedding 文本嵌入。
    # 两者接口结构不同，不能共用一个配置。
    kind: Literal["chat", "embedding"] = "chat"
    # 嵌入向量维度。聊天模型忽略此字段；嵌入模型首版固定 1024，
    # 必须与知识库向量列一致，否则写入数据库会失败。
    dimensions: int | None = Field(default=None, ge=1, le=8192)
    base_url: str = Field(min_length=1, max_length=255)
    # 只在新增时必填；编辑时留空表示保留原密钥。
    api_key: str = Field(min_length=1, max_length=300)
    model: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    # 数字越小越先尝试。范围限制是为了避免误填超大值导致排序不直观。
    priority: int = Field(default=100, ge=0, le=9999)
    timeout_seconds: int = Field(default=20, ge=3, le=120)
    max_output_tokens: int = Field(default=800, ge=100, le=4000)

    @model_validator(mode="after")
    def _normalize_kind(self):
        if self.kind == "embedding":
            # 不填时给默认值，减少运营需要记住的参数。
            if self.dimensions is None:
                self.dimensions = 1024
            if self.dimensions != 1024:
                raise ValueError("嵌入模型维度必须为 1024，与知识库向量列保持一致")
        else:
            # 聊天模型没有向量维度概念，统一清空，避免展示与使用混乱。
            self.dimensions = None
        return self


class AIProviderUpdateRequest(CamelModel):
    """编辑模型供应商。所有字段可选，只更新传了的字段。

    api_key 特殊约定：不传、传空字符串都表示“保留原密钥”。
    这样前端编辑页不必回填明文密钥（也不应该回填），
    运营只改模型名或优先级时不会把密钥清掉。
    """

    name: str | None = Field(default=None, min_length=1, max_length=40)
    provider_type: Literal["openai_compatible"] | None = None
    kind: Literal["chat", "embedding"] | None = None
    dimensions: int | None = Field(default=None, ge=1, le=8192)
    base_url: str | None = Field(default=None, min_length=1, max_length=255)
    api_key: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, min_length=1, max_length=80)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=9999)
    timeout_seconds: int | None = Field(default=None, ge=3, le=120)
    max_output_tokens: int | None = Field(default=None, ge=100, le=4000)


class KbIndexVersionCreateRequest(CamelModel):
    """新知识库索引版本。

    切片长度与重叠长度决定检索粒度：
    - 片段太短：上下文不完整，模型拿到的信息支离破碎；
    - 片段太长：一个片段混合多个主题，检索精度下降；
    - 重叠太小：一句话被切断后两边都检索不到。
    400 字与 80 字是首版经过测试的起点，运营可以新建版本对比效果。
    """

    name: str = Field(min_length=1, max_length=80)
    chunk_size: int = Field(default=400, ge=200, le=1000)
    chunk_overlap: int = Field(default=80, ge=0, le=200)

    @model_validator(mode="after")
    def _check_overlap(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("重叠长度必须小于切片长度")
        return self


class KbSearchTestRequest(CamelModel):
    """知识库检索测试。

    threshold 是最低相似度：低于该值的片段不返回。
    阈值太低会返回大量无关内容，太高又可能什么都搜不到，
    因此提供给运营现场调整，默认 0 表示先看全量排序。
    """

    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)
    threshold: float = Field(default=0.0, ge=0.0, le=1.0)


class AdminLoginRequest(CamelModel):
    """管理员登录请求。

    与普通用户登录完全分开：这里使用用户名 + 密码，
    不使用手机号验证码，避免后台账号与用户手机号体系耦合。
    """

    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=8, max_length=128)


class ReasonRequest(CamelModel):
    """需要说明原因的后台操作。

    拒绝饭帖、下架内容、封禁用户都必须填写原因，
    审计日志中会原样保存，便于事后追责和向用户解释。
    """

    reason: str = Field(min_length=2, max_length=200)


class BatchReviewRequest(CamelModel):
    """批量审核请求。

    为什么限制一次最多 20 条：批量操作会逐条写审计日志并提交事务，
    条数过多会长时间占用数据库连接；20 条既能提升效率，也能保证失败可解释。
    """

    post_ids: list[str] = Field(min_length=1, max_length=20)
    action: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _dedupe_and_validate(self):
        # 去重但保留顺序，避免同一帖子在一次请求里被处理两次。
        self.post_ids = list(dict.fromkeys(self.post_ids))
        if self.action == "reject" and len((self.reason or "").strip()) < 2:
            raise ValueError("批量拒绝需要填写至少 2 个字的原因")
        return self


class AnalyticsEventItem(CamelModel):
    """单条客户端埋点。

    eventId 由客户端生成，服务端用它做幂等：网络重试不会重复计数。
    这里不接收 accountId，登录用户由后端从令牌解析，防止客户端伪造归属。
    """

    event_id: str = Field(min_length=8, max_length=64)
    event_name: str = Field(min_length=2, max_length=40)
    page_name: str | None = Field(default=None, max_length=40)
    platform: str | None = Field(default=None, max_length=20)
    app_version: str | None = Field(default=None, max_length=20)
    session_ref: str | None = Field(default=None, max_length=64)
    request_id: str | None = Field(default=None, max_length=64)
    occurred_at: datetime | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class AnalyticsBatchRequest(CamelModel):
    """批量上报。单批最多 50 条，客户端失败后可整批重试。"""

    events: list[AnalyticsEventItem] = Field(min_length=1, max_length=50)


class RecipeIngredientInput(CamelModel):
    name: str = Field(min_length=1, max_length=40)
    amount: str = Field(min_length=1, max_length=40)


class RecipeInput(CamelModel):
    """后台新增或编辑菜谱。

    菜谱是平台内容，不接收客户端传来的发布者编号。
    mainIngredients 允许不填，后端会从 ingredients 的前三个名称派生，
    避免运营重复录入同一份信息。
    """

    title: str = Field(min_length=1, max_length=40)
    cover_url: str = Field(min_length=1, max_length=255)
    # 外部导入的菜谱可能没有写总时长，所以允许为空。
    # 手工创建时前端仍会要求填写，后端不再强制。
    total_minutes: int | None = Field(default=None, ge=1, le=180)
    tool_codes: list[str] = Field(default_factory=list, max_length=8)
    category_codes: list[str] = Field(default_factory=list, max_length=8)
    servings: float = Field(default=1, gt=0, le=20)
    main_ingredients: list[str] = Field(default_factory=list, max_length=3)
    ingredients: list[RecipeIngredientInput] = Field(min_length=1, max_length=30)
    steps: list[str] = Field(min_length=1, max_length=30)
    preconditions: str | None = Field(default=None, max_length=200)
    content_origin: Literal["platform", "editor", "howtocook", "pdf"] = "platform"
    validation_status: Literal["tested", "pending", "not_tested"] = "pending"
    status: Literal["draft", "published", "archived"] = "published"

    @model_validator(mode="after")
    def _clean(self):
        self.title = self.title.strip()
        self.cover_url = self.cover_url.strip()
        self.steps = [item.strip() for item in self.steps if item.strip()]
        self.tool_codes = list(
            dict.fromkeys(code.strip() for code in self.tool_codes if code.strip())
        )
        self.category_codes = list(
            dict.fromkeys(code.strip() for code in self.category_codes if code.strip())
        )
        invalid = [item.name for item in self.ingredients if not item.name.strip()]
        if invalid:
            raise ValueError("食材名称不能为空")
        if not self.steps:
            raise ValueError("至少需要填写一个步骤")
        if not self.main_ingredients:
            self.main_ingredients = [
                item.name.strip()[:12] for item in self.ingredients[:3]
            ]
        else:
            self.main_ingredients = [
                name.strip() for name in self.main_ingredients if name.strip()
            ][:3]
        return self


class TasteTagCreateRequest(CamelModel):
    """口味标签字典新增。

    标签名称是字典的主键语义，创建后不允许改名，
    否则历史饭帖里的 JSON 标签会变成孤儿数据。
    """

    name: str = Field(min_length=1, max_length=16)
    sort_order: int = Field(default=100, ge=0, le=9999)
    enabled: bool = True

    @model_validator(mode="after")
    def _clean(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("标签名称不能为空")
        return self


class TasteTagUpdateRequest(CamelModel):
    """标签维护只允许调整排序和启停，避免改名破坏历史数据。"""

    sort_order: int | None = Field(default=None, ge=0, le=9999)
    enabled: bool | None = None


class AdminCreateRequest(CamelModel):
    """新增管理员。密码只在这里出现一次，服务端只保存 Argon2id 哈希。"""

    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{2,40}$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=40)
    role_ids: list[str] = Field(min_length=1, max_length=10)


class AdminUpdateRequest(CamelModel):
    """编辑管理员。字段全部可选，只更新传了的字段。"""

    display_name: str | None = Field(default=None, min_length=1, max_length=40)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    status: Literal["active", "disabled"] | None = None
    role_ids: list[str] | None = Field(default=None, max_length=10)


class AdminRoleRequest(CamelModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,39}$")
    name: str = Field(min_length=1, max_length=40)
    permissions: list[str] = Field(default_factory=list, max_length=40)


class AdminRoleUpdateRequest(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    permissions: list[str] | None = Field(default=None, max_length=40)

