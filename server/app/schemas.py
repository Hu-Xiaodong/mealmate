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


class CreatePostRequest(CamelModel):
    title: str = Field(min_length=1, max_length=24)
    review: str = Field(min_length=1, max_length=200)
    source: Literal["self", "takeaway", "dine_in"]
    image_asset_ids: list[str] = Field(min_length=1, max_length=9)
    author_recipe: AuthorRecipeInput | None = None
    takeaway_store: str | None = Field(default=None, max_length=80)
    dine_in_address: str | None = Field(default=None, max_length=160)
    location: LocationInput | None = None

    @model_validator(mode="after")
    def _branch_validation(self):
        self.title = self.title.strip()
        self.review = self.review.strip()
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

        # 只有用户明确同意公开时才保留粗略坐标，且只保留三位小数（约百米级）。
        if self.location is None or not self.location.public_consent:
            self.location = None
        else:
            self.location.lat = round(self.location.lat, 3)
            self.location.lng = round(self.location.lng, 3)
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

