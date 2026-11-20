"""腾讯位置服务（腾讯地图 WebService API）的封装。

为什么由后端调用地图接口，而不是客户端直接调：
1. 密钥（Key）只存在服务端，客户端无法拿到，避免被盗刷额度；
2. Flutter App、小程序、H5 共用同一套代理，不用分别申请和配置密钥；
3. 可以统一处理超时、错误码与缓存响应头。

为什么只接腾讯一家，而不是同时接腾讯和高德做“双地图”：
1. 双供应商意味着两套请求参数、两套响应结构、两套错误码都要维护，
   每新增一个地图能力都要写两遍适配和两遍测试，代码量和出 bug 的面积翻倍；
2. 两家的兴趣点编号、距离精度、配额、甚至坐标顺序都不同，
   混用容易出现“同一家店出现两条数据”“导航位置偏一点”这类难排查的问题；
3. 个人项目每天的实际调用量远低于单家的免费额度，多接一家没有收益；
4. 真要换供应商时，因为客户端只认后端定义的统一结构（name/address/lat/lng），
   只需替换本文件的实现，客户端完全不用改——这正是多一层代理的价值。

腾讯位置服务使用 HTTP 接口，返回 JSON 或图片，不依赖任何原生地图 SDK，
因此 Flutter 不需要额外地图插件，小程序也不需要额外地图组件。
"""

import hashlib
import logging
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)

# 腾讯地图所有 WebService 接口共用的域名。
TENCENT_MAP_BASE_URL = "https://apis.map.qq.com"

# 附近搜索的半径，单位米。
# 腾讯地点搜索的 nearby 语法要求半径在 10 到 1000 米之间，超过 1000 会直接返回参数错误，
# 所以这里取上限 1000，再配合 auto_extend=1 让腾讯在没有结果时自动扩大范围。
NEARBY_RADIUS_METERS = 1000

# 静态地图上标记点的颜色，使用 App 主色（橙红），十六进制写法为 0xRRGGBB。
# 传这个参数只是让图片观感统一，不影响功能。
MARKER_COLOR = "0xCC462C"


def _require_key() -> str:
    """检查腾讯地图密钥是否配置，并返回它。

    没有配置时返回 503 而不是 500：
    这是“依赖服务未就绪”，不是代码崩溃，客户端可以据此降级为手动填写地址。
    """
    if not settings.tencent_map_key:
        raise AppError(
            "MAP_NOT_CONFIGURED",
            "地图服务暂未配置，可以先手动填写地址",
            status_code=503,
        )
    return settings.tencent_map_key


def _signature(path: str, params: dict[str, Any]) -> str | None:
    """按腾讯规则计算 MD5 签名，返回 sig 参数。

    为什么需要签名：
    Key 只证明“这是哪个应用在调用”，一旦 Key 泄露，别人就能拿你的额度去刷。
    Secret Key（SK）不参与网络传输，只用来证明“请求确实由持有 SK 的服务端发出”。
    控制台开启“签名校验”后，每个请求都要带上用 SK 计算的 sig，否则返回状态码 111。

    腾讯的签名规则（GET 请求）：
    1. 取请求路径，例如 /ws/place/v1/search；
    2. 把所有参数按参数名从小到大排序；
    3. 用“参数名=原始值”并用 & 连接，值必须是未编码的原始数据；
    4. 拼成“路径?排序后的参数+SK”，对整串做 MD5，得到 32 位小写十六进制字符串。

    返回 None 表示没有配置 SK，即控制台没有开启签名校验，请求不需要 sig。
    """
    secret_key = settings.tencent_map_secret_key
    if not secret_key:
        return None
    pairs = "&".join(f"{name}={params[name]}" for name in sorted(params))
    raw = f"{path}?{pairs}{secret_key}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    """把接口返回的字段安全地转成字符串。

    腾讯地点搜索在字段缺失时可能返回 null，直接给前端渲染会显示 "null"，
    所以统一在这里转成空字符串。地址为空是正常情况（有些兴趣点没有登记地址），
    不应该因此丢弃整条结果。
    """
    return value if isinstance(value, str) else ""


def parse_place_items(body: dict[str, Any]) -> list[dict[str, Any]]:
    """把腾讯地点搜索的响应体转换成项目统一的字段结构。

    单独抽成函数的目的：
    1. 解析逻辑不依赖网络，可以直接用一份固定的响应报文做单元测试；
    2. 将来更换地图供应商时，只需要重写这一个函数和请求参数；
    3. 客户端只认识这里的 name/address/lat/lng/distanceMeters，
       不会绑死在某家服务商的字段名上。

    腾讯响应里每条数据长这样（只列本项目用到的字段）：
    {
        "id": "1234567890",
        "title": "老王牛肉粉",
        "address": "演示路 12 号",
        "location": {"lat": 31.2286, "lng": 121.469},
        "_distance": 320
    }
    注意：腾讯的坐标对象是“纬度 lat、经度 lng”两个独立字段，
    和高德返回的 "经度,纬度" 字符串不同，不需要再拆分字符串。
    """
    items = body.get("data") or []
    places: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        location = item.get("location")
        if not isinstance(location, dict):
            # 没有坐标的地点无法生成静态地图，也无法导航，直接跳过。
            continue
        try:
            poi_lat = float(location.get("lat"))
            poi_lng = float(location.get("lng"))
        except (TypeError, ValueError):
            continue
        distance = item.get("_distance")
        # 距离单位是米。只有传了中心点坐标，腾讯才会返回 _distance；
        # 没有传坐标时该字段不存在，这里保留为空，前端不显示距离即可。
        distance_meters = int(distance) if isinstance(distance, (int, float)) else None
        places.append(
            {
                "id": _text(item.get("id")),
                "name": _text(item.get("title")),
                "address": _text(item.get("address")),
                "lat": poi_lat,
                "lng": poi_lng,
                "distanceMeters": distance_meters,
            }
        )
    return places


async def search_places(
    keyword: str,
    *,
    lat: float | None = None,
    lng: float | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """按关键词搜索地点，返回统一结构。

    使用腾讯的“地点搜索”接口（/ws/place/v1/search），
    这是 WebService 里最常用的兴趣点搜索接口，支持按城市范围或按中心点附近搜索。

    搜索范围必须带经纬度，使用 nearby(纬度,经度,半径,是否自动扩大)：
    半径上限 1000 米，auto_extend=1 表示附近搜不到时自动扩大范围，
    避免用户在店里却因为坐标偏移而搜不到目标店铺。

    为什么不做“全国搜索”兜底：
    腾讯的地点搜索不支持“全国”这种范围，region 必须给具体城市名或城市编码。
    传 region(全国,0) 时接口会返回成功但结果为空，用户会误以为没有这家店。
    所以这里要求客户端先定位；没有定位时返回明确的 400，
    让客户端提示用户开启定位，而不是静默返回空列表。

    坐标顺序是最容易写错的地方：
    腾讯统一使用“纬度在前、经度在后”（lat,lng），
    而高德使用“经度在前、纬度在后”，两家正好相反，切换供应商时必须同步修改。
    """
    key = _require_key()
    # 签名校验对 # % & 这类特殊字符很敏感：它们会破坏“参数名=值”的拼接结构。
    # 腾讯官方建议在端上过滤，店名里出现这些字符的概率极低，过滤掉不影响搜索。
    keyword = keyword.replace("#", "").replace("%", "").replace("&", "").strip()
    if not keyword:
        raise AppError("KEYWORD_REQUIRED", "请输入要搜索的店铺名称")
    params: dict[str, Any] = {
        "key": key,
        "keyword": keyword,
        # 腾讯单页最多 20 条，page_size 超过 20 会被截断或报参数错误。
        "page_size": min(max(limit, 1), 20),
        "page_index": 1,
        # 明确要求返回 JSON，避免默认行为返回其他格式。
        "output": "json",
    }
    if lat is None or lng is None:
        raise AppError(
            "LOCATION_REQUIRED",
            "请先开启定位后再搜索店铺",
            status_code=400,
        )
    params["boundary"] = f"nearby({lat:.6f},{lng:.6f},{NEARBY_RADIUS_METERS},1)"
    # 按距离由近到远排序，保证最近的分店排在最前面。
    params["orderby"] = "_distance"

    # 注意：sig 必须在参数排序之前算好，再把 sig 加进参数一起发送；
    # 如果把 sig 也参与排序和计算，就会陷入“签名需要包含签名本身”的死循环。
    sig = _signature("/ws/place/v1/search", params)
    if sig:
        params["sig"] = sig

    try:
        async with httpx.AsyncClient(timeout=settings.map_timeout_seconds) as client:
            response = await client.get(
                f"{TENCENT_MAP_BASE_URL}/ws/place/v1/search", params=params
            )
    except httpx.HTTPError as exc:
        raise AppError(
            "MAP_UPSTREAM_ERROR", "地图服务暂时不可用，请稍后重试", status_code=502
        ) from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise AppError(
            "MAP_UPSTREAM_ERROR", "地图服务返回了无法解析的内容", status_code=502
        ) from exc

    # 腾讯用 status=0 表示成功，非 0 表示失败（例如 120 表示配额超限、311 表示密钥错误）。
    # 这里统一转成 502，不把腾讯的原始错误码暴露给客户端：
    # 客户端只需要知道“地图暂时不可用”，具体原因应该看后端日志或监控。
    if response.status_code != 200 or str(body.get("status")) != "0":
        # 原始错误码只写日志，不返回给客户端：
        # 110 来源未授权、111 签名失败、120 每秒超限、121 当天配额用完，
        # 这些是运维和开发需要看的信息，普通用户只需要知道“地图暂时不可用”。
        logger.warning(
            "腾讯地点搜索失败 http=%s status=%s message=%s",
            response.status_code,
            body.get("status"),
            body.get("message"),
        )
        raise AppError(
            "MAP_UPSTREAM_ERROR",
            "地图服务暂时不可用，请稍后重试",
            status_code=502,
        )

    return parse_place_items(body)


async def static_map(
    *, lat: float, lng: float, zoom: int, width: int, height: int
) -> bytes:
    """代理腾讯静态地图，直接返回图片字节。

    静态地图是一张带标记的图片，不需要 JavaScript，也不需要地图 SDK。
    对“详情页展示店铺位置”这种只读场景足够，而且客户端实现非常简单：
    一个普通的图片地址就能显示。

    由后端转发还有一个好处：密钥不会出现在图片地址里，
    用户右键查看图片地址也拿不到密钥。

    腾讯静态地图第二版（/ws/staticmap/v2/）的关键参数：
    - center：地图中心点，格式为“纬度,经度”；
    - zoom：缩放级别，数字越大越近；
    - size：图片尺寸，格式为“宽*高”；
    - markers：标记点，用竖线分隔多个样式项，最后一项是“纬度,经度”；
    - maptype：地图类型，roadmap 表示普通道路图。
    """
    key = _require_key()
    params = {
        "key": key,
        "center": f"{lat:.6f},{lng:.6f}",
        "zoom": zoom,
        "size": f"{width}*{height}",
        # markers 的样式项：size 控制图标大小，color 控制颜色，label 是图标上的字母。
        # 这里只放一个标记点，正好标出店铺位置。
        "markers": f"size:large|color:{MARKER_COLOR}|label:A|{lat:.6f},{lng:.6f}",
        "maptype": "roadmap",
    }
    # 静态地图的请求路径带有结尾斜杠，签名里的路径必须与真实请求完全一致，
    # 否则腾讯计算出的签名会对不上（这是签名校验最常见的坑之一）。
    sig = _signature("/ws/staticmap/v2/", params)
    if sig:
        params["sig"] = sig
    try:
        async with httpx.AsyncClient(timeout=settings.map_timeout_seconds) as client:
            response = await client.get(
                f"{TENCENT_MAP_BASE_URL}/ws/staticmap/v2/", params=params
            )
    except httpx.HTTPError as exc:
        raise AppError(
            "MAP_UPSTREAM_ERROR", "地图服务暂时不可用，请稍后重试", status_code=502
        ) from exc

    content_type = response.headers.get("content-type", "")
    # 成功时返回图片；失败时腾讯会返回 JSON 错误信息（例如配额超限、密钥错误），
    # 所以不能只看状态码，还要看内容类型是不是图片。
    if response.status_code != 200 or not content_type.startswith("image/"):
        # 静态地图失败时返回的是 JSON，把前 200 个字符写进日志，便于定位配额或签名问题。
        logger.warning(
            "腾讯静态地图失败 http=%s content_type=%s body=%s",
            response.status_code,
            content_type,
            response.text[:200],
        )
        raise AppError(
            "MAP_UPSTREAM_ERROR",
            "地图图片暂时无法生成，请稍后重试",
            status_code=502,
        )
    return response.content
