import json
from typing import Any

from redis.asyncio import Redis as AsyncRedis


def build_order_cache_key(order_id: int) -> str:
    return f"orders:by_id:{order_id}"


async def cache_set_order(
    redis: AsyncRedis,
    order_id: int,
    payload: dict[str, Any],
    ttl_seconds: int = 60,
) -> None:
    key = build_order_cache_key(order_id)
    value = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    await redis.set(key, value, ex=ttl_seconds)


async def cache_get_order(redis: AsyncRedis, order_id: int) -> dict[str, Any] | None:
    key = build_order_cache_key(order_id)
    raw = await redis.get(key)
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


async def cache_invalidate_order(redis: AsyncRedis, order_id: int) -> None:
    key = build_order_cache_key(order_id)
    await redis.delete(key)
