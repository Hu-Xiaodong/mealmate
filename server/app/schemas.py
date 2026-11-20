"""请求体模型。响应由 serializer 输出 camelCase 字典。"""

from typing import Literal

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


# 口味标签使用固定枚举，而不是让用户自由输入。
# 原因：自由输入会产生“辣”“有点辣”“微辣口”等同义标签，无法筛选也无法统计。
# 新增口味时必须同时改后端枚举与前端选项，保证两端永远一致。
TasteTag = Literal[
    "清淡",
    "重口下饭",
    "微辣",
    "特辣",
    "酸甜",
    "咸鲜",
    "油炸",
    "烧烤",
    "汤羹",
    "面食",
]


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
    taste_tags: list[TasteTag] = Field(default_factory=list, max_length=3)
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
    taste_tags: list[TasteTag] = Field(default_factory=list, max_length=3)
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

