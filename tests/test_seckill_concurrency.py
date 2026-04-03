"""High-concurrency seckill integration test (real MySQL + Redis, no mocks).

Uses httpx.AsyncClient with ASGITransport to issue many concurrent POST /attempt
calls against the FastAPI app. Asserts Lua pre-deduct never grants more ACCEPTED
than seeded stock, then drains the Redis stream with consume_once and asserts
MySQL order count and db_sold match.

Requires MYSQL_* and REDIS_URL (see project docs); alembic upgrade runs via conftest.
"""

from __future__ import annotations

import asyncio
import datetime
import uuid
from collections import Counter

import httpx
from httpx import ASGITransport
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from orders.core.db.models import SeckillActivity, SeckillOrder, SeckillStockLedger
from orders.core.db.session import SessionMaker
from orders.core.settings import settings
from orders.main import app
from orders.seckill.consumer import SECKILL_STREAM_KEY, consume_once
from orders.seckill.keys import req_key, result_key, stock_key

# Keep moderate so CI/local stays fast; still exercises concurrent Lua + HTTP.
SECKILL_STOCK = 25
CONCURRENT_ATTEMPTS = 200


async def _insert_activity(session: AsyncSession) -> int:
    now = datetime.datetime.now(datetime.UTC)
    activity = SeckillActivity(
        sku_id=999001,
        start_at=now,
        end_at=now + datetime.timedelta(hours=1),
        status="online",
        total_stock=SECKILL_STOCK,
        db_sold=0,
    )
    session.add(activity)
    await session.flush()
    return int(activity.id)


async def _cleanup_activity(session: AsyncSession, activity_id: int) -> None:
    await session.execute(
        delete(SeckillOrder).where(SeckillOrder.activity_id == activity_id)
    )
    await session.execute(
        delete(SeckillStockLedger).where(
            SeckillStockLedger.activity_id == activity_id
        )
    )
    await session.execute(
        delete(SeckillActivity).where(SeckillActivity.id == activity_id)
    )


async def _count_orders(session: AsyncSession, activity_id: int) -> int:
    stmt = select(func.count()).select_from(SeckillOrder).where(
        SeckillOrder.activity_id == activity_id
    )
    return int(await session.scalar(stmt) or 0)


async def _get_db_sold(session: AsyncSession, activity_id: int) -> int:
    row = await session.get(SeckillActivity, activity_id)
    if row is None:
        return -1
    return int(row.db_sold)


async def _drain_consumer(redis_client: AsyncRedis, max_rounds: int) -> int:
    processed = 0
    for _ in range(max_rounds):
        ok = await consume_once(redis_client=redis_client)
        if not ok:
            break
        processed += 1
    return processed


def test_seckill_concurrent_attempts_respect_stock_and_db() -> None:
    asyncio.run(_run_concurrency_case())


async def _run_concurrency_case() -> None:
    activity_id: int | None = None
    request_ids: list[str] = []
    redis_client = AsyncRedis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with SessionMaker() as session:
            async with session.begin():
                activity_id = await _insert_activity(session)

        assert activity_id is not None
        aid = activity_id

        await redis_client.delete(SECKILL_STREAM_KEY)
        await redis_client.set(stock_key(aid), SECKILL_STOCK)

        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=60.0
        ) as client:

            async def one_attempt(idx: int) -> str:
                rid = f"hc-{uuid.uuid4().hex}"
                request_ids.append(rid)
                resp = await client.post(
                    f"/seckill/{aid}/attempt",
                    json={"user_id": idx + 1, "request_id": rid},
                )
                resp.raise_for_status()
                return str(resp.json()["code"])

            codes = await asyncio.gather(
                *[one_attempt(i) for i in range(CONCURRENT_ATTEMPTS)]
            )

        counts = Counter(codes)
        accepted = counts.get("ACCEPTED", 0)
        sold_out = counts.get("SOLD_OUT", 0)
        duplicate = counts.get("DUPLICATE", 0)

        assert duplicate == 0, "unique request_id must not DUPLICATE"
        assert accepted == SECKILL_STOCK, (
            f"expected exactly {SECKILL_STOCK} ACCEPTED, got {accepted}"
        )
        assert accepted + sold_out == CONCURRENT_ATTEMPTS

        final_stock = await redis_client.get(stock_key(aid))
        assert final_stock == "0", f"redis stock should be 0, got {final_stock}"

        drained = await _drain_consumer(redis_client, max_rounds=SECKILL_STOCK + 50)
        assert drained == SECKILL_STOCK

        stream_len = await redis_client.xlen(SECKILL_STREAM_KEY)
        assert stream_len == 0

        async with SessionMaker() as session:
            order_n = await _count_orders(session, aid)
            db_sold = await _get_db_sold(session, aid)

        assert order_n == SECKILL_STOCK
        assert db_sold == SECKILL_STOCK

    finally:
        if activity_id is not None:
            async with SessionMaker() as session:
                async with session.begin():
                    await _cleanup_activity(session, activity_id)
        for rid in request_ids:
            await redis_client.delete(req_key(activity_id, rid))
            await redis_client.delete(result_key(activity_id, rid))
        if activity_id is not None:
            await redis_client.delete(stock_key(activity_id))
        await redis_client.delete(SECKILL_STREAM_KEY)
        await redis_client.aclose()

