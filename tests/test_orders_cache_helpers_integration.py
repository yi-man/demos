import asyncio
from decimal import Decimal

import redis.asyncio as redis_asyncio

from orders.core.cache.order_cache import (
    build_order_cache_key,
    cache_get_order,
    cache_invalidate_order,
    cache_set_order,
)
from orders.core.settings import settings


def test_cache_set_get_invalidate_roundtrip() -> None:
    async def run() -> None:
        r = redis_asyncio.Redis.from_url(settings.redis_url)
        order_id = 999
        key = build_order_cache_key(order_id)

        try:
            await r.delete(key)

            payload = {"id": order_id, "amount": Decimal("1.23")}
            await cache_set_order(r, order_id, payload, ttl_seconds=5)

            got = await cache_get_order(r, order_id)
            assert got is not None
            assert got["id"] == order_id
            # Decimal is converted via `default=str` in cache_set_order
            assert got["amount"] == "1.23"

            await cache_invalidate_order(r, order_id)
            exists = await r.exists(key)
            assert exists == 0
        finally:
            await r.aclose()

    asyncio.run(run())

