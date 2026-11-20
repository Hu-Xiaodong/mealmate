"""地图接口：配置探测、地点搜索、静态地图代理（底层为腾讯位置服务）。

三个接口分别解决三个问题：
1. /config：客户端启动时先问后端“地图可用吗”，不可用就降级为手动填地址；
2. /places：发布页搜索店铺，拿到名称、地址和坐标；
3. /static：详情页展示一张带标记的静态地图，不需要地图 SDK。
"""

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.errors import AppError
from app.core.responses import ok
from app.db.models import User
from app.services.map_service import search_places, static_map

router = APIRouter(prefix="/maps", tags=["maps"])


@router.get("/config")
async def map_config():
    """返回地图功能是否可用。

    这里不直接暴露 Key，也不返回供应商名称，
    客户端只需要知道“能不能用”，从而决定显示地图选点还是纯手工输入。
    """
    return ok({"enabled": bool(settings.tencent_map_key)})


@router.get("/places")
async def map_places(
    keyword: str = Query(min_length=1, max_length=60),
    lat: float | None = Query(default=None, ge=-90, le=90),
    lng: float | None = Query(default=None, ge=-180, le=180),
    limit: int = Query(default=10, ge=1, le=20),
    _: User = Depends(get_current_user),
):
    """按关键词搜索地点。

    要求登录的原因：这个接口会消耗地图服务的调用额度，
    如果完全公开，容易被当成免费的 POI 搜索代理刷额度。
    静态地图则保持公开，因为详情页的访客也可能需要看地图。
    """
    if (lat is None) != (lng is None):
        raise AppError("LOCATION_INVALID", "纬度和经度需要同时提供")
    keyword = keyword.strip()
    if not keyword:
        raise AppError("KEYWORD_REQUIRED", "请输入要搜索的店铺名称")
    items = await search_places(keyword, lat=lat, lng=lng, limit=limit)
    return ok({"items": items})


@router.get("/static")
async def map_static(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    zoom: int = Query(default=16, ge=3, le=18),
    width: int = Query(default=640, ge=100, le=1024),
    height: int = Query(default=320, ge=100, le=1024),
):
    """返回静态地图图片。

    响应设置一天的浏览器缓存：
    同一家店的地图不会频繁变化，缓存可以显著减少地图服务调用次数。
    """
    data = await static_map(lat=lat, lng=lng, zoom=zoom, width=width, height=height)
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
