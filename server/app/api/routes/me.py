from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.serializers import iso
from app.core.responses import ok
from app.db.models import User, UserLocation
from app.db.session import get_db
from app.schemas import SaveLocationRequest
from app.services.me_service import draft_detail, my_drafts, my_favorites, my_posts
from app.utils.time import now_utc

router = APIRouter(prefix="/me", tags=["me"])


def _location_payload(location: UserLocation | None) -> dict:
    """把定位记录转成前端需要的 camelCase 结构。

    没有记录时返回 null，前端据此判断“没有历史定位”，
    而不是靠“经纬度是不是 0”这种容易误判的方式。
    """
    if location is None:
        return {"location": None}
    return {
        "location": {
            "lat": location.lat,
            "lng": location.lng,
            "area": location.area,
            "updatedAt": iso(location.updated_at),
        }
    }


@router.get("/location")
async def my_location(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """读取当前账号最近一次保存的定位。

    只按登录身份查询，不接收任何用户编号参数，
    因此不存在“通过改参数读别人定位”的越权可能。
    """
    return ok(_location_payload(await db.get(UserLocation, user.id)))


@router.put("/location")
async def save_my_location(
    body: SaveLocationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """保存/覆盖当前账号的最近一次定位。

    用 PUT 而不是 POST：同一个账号永远只有一条记录，
    重复提交就是“覆盖成最新值”，这符合 PUT 的语义，也方便客户端失败重试。
    """
    location = await db.get(UserLocation, user.id)
    if location is None:
        location = UserLocation(account_id=user.id)
        db.add(location)
    # 定位精度保留 6 位小数（约 0.1 米），足够选店使用；
    # 不使用饭帖“公开大概位置”的三位小数，因为这个数据只有本人可见，不需要刻意模糊。
    location.lat = round(body.lat, 6)
    location.lng = round(body.lng, 6)
    location.area = (body.area or "").strip() or None
    # 显式更新时间：SQLite 等数据库对 onupdate 的支持不如 PostgreSQL 稳定，
    # 这里手动赋值可以保证测试环境与生产环境行为一致。
    location.updated_at = now_utc()
    await db.commit()
    await db.refresh(location)
    return ok(_location_payload(location))


@router.get("/posts")
async def mine_posts(
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await my_posts(db, user, cursor, limit))


@router.get("/drafts")
async def mine_drafts(
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await my_drafts(db, user, cursor, limit))


@router.get("/drafts/{post_id}")
async def mine_draft_detail(
    post_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await draft_detail(db, user, post_id))


@router.get("/favorites")
async def mine_favorites(
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await my_favorites(db, user, cursor, limit))
