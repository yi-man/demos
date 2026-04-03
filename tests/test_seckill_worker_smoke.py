from __future__ import annotations

import asyncio
import datetime
import uuid

from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import delete, select

from orders.core.db.models import SeckillActivity, SeckillOrder, SeckillStockLedger
from orders.core.db.session import SessionMaker
from orders.core.settings import settings
from orders.seckill.consumer import SECKILL_STREAM_KEY
from orders.seckill.keys import result_key, stock_key
from orders.seckill.worker import run_consumer_loop


def test_seckill_worker_consumes_one_event() -> None:
    asyncio.run(_run_one_event_case())


async def _run_one_event_case() -> None:
    now = datetime.datetime.now(datetime.UTC)
    activity_id: int | None = None
    request_id = f"worker-{uuid.uuid4().hex}"
    try:
        async with SessionMaker() as session:
            async with session.begin():
                activity = SeckillActivity(
                    sku_id=12345,
                    start_at=now,
                    end_at=now + datetime.timedelta(minutes=10),
                    status="online",
                    total_stock=1,
                    db_sold=0,
                )
                session.add(activity)
                await session.flush()
                activity_id = int(activity.id)

        assert activity_id is not None

        redis_client = AsyncRedis.from_url(settings.redis_url, decode_responses=True)
        try:
            await redis_client.delete(SECKILL_STREAM_KEY)
            await redis_client.delete(stock_key(activity_id))
            await redis_client.delete(result_key(activity_id, request_id))

            await redis_client.set(stock_key(activity_id), 1)
            await redis_client.xadd(
                SECKILL_STREAM_KEY,
                {
                    "activity_id": str(activity_id),
                    "user_id": "1",
                    "request_id": request_id,
                },
            )

            await run_consumer_loop(
                redis_client,
                max_rounds=1,
                sleep_when_empty_s=0.01,
            )

            result = await redis_client.get(result_key(activity_id, request_id))
            assert result == "SUCCESS"
        finally:
            await redis_client.aclose()

        async with SessionMaker() as session:
            order_rows = await session.execute(
                select(SeckillOrder).where(
                    (SeckillOrder.activity_id == activity_id)
                    & (SeckillOrder.request_id == request_id)
                )
            )
            order_count = len(order_rows.scalars().all())
            assert order_count == 1

            ledger_rows = await session.execute(
                select(SeckillStockLedger).where(
                    (SeckillStockLedger.activity_id == activity_id)
                    & (SeckillStockLedger.biz_id == request_id)
                    & (SeckillStockLedger.delta == -1)
                )
            )
            ledger_count = len(ledger_rows.scalars().all())
            assert ledger_count == 1
    finally:
        if activity_id is not None:
            async with SessionMaker() as session:
                async with session.begin():
                    await session.execute(
                        delete(SeckillStockLedger).where(
                            SeckillStockLedger.activity_id == activity_id
                        )
                    )
                    await session.execute(
                        delete(SeckillOrder).where(
                            SeckillOrder.activity_id == activity_id
                        )
                    )
                    await session.execute(
                        delete(SeckillActivity).where(SeckillActivity.id == activity_id)
                    )
