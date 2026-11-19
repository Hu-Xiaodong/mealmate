"""Redis 可选缓存。连接不可用时自动降级，不影响只读浏览。"""

import json
from typing import Any

from redis.asyncio import Redis

from app.core.config import settings

_client: Redis | None = None
_disabled = not bool(settings.redis_url)


def _get_client() -> Redis | None:
    global _client
    if _disabled:
        return None
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def get_json(key: str) -> Any | None:
    client = _get_client()
    if client is None:
        return None
    try:
        raw = await client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


async def set_json(key: str, value: Any, ttl_seconds: int) -> None:
    client = _get_client()
    if client is None:
        return
    try:
        await client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)
    except Exception:
        return


async def delete_key(key: str) -> None:
    """删除指定缓存键。

    审核通过或下架后必须让热榜缓存立即失效，否则用户会继续看到旧排名。
    Redis 未配置时直接跳过，不影响主流程。
    """
    client = _get_client()
    if client is None:
        return
    try:
        await client.delete(key)
    except Exception:
        return


async def close_cache() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
