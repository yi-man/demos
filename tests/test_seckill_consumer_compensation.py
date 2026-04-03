from __future__ import annotations

import asyncio
import datetime
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import select

from orders.core.db.models import SeckillActivity, SeckillOrder, SeckillStockLedger
from orders.core.db.session import SessionMaker
from orders.core.settings import settings
from orders.seckill.compensation import reconcile_once
from orders.seckill.consumer import SECKILL_STREAM_KEY, consume_once
from orders.seckill.keys import result_key, stock_key


def test_consumer_confirms_order_once() -> None:
    asyncio.run(_run_consumer_confirmation_case())


def test_compensation_rolls_back_redis_when_db_order_missing() -> None:
    asyncio.run(_run_compensation_rollback_case())


async def _run_consumer_confirmation_case() -> None:
    activity_id = await _prepare_activity()
    request_id = f"req-consumer-{uuid4().hex}"
    user_id = 123

    await _run_consumer_once(
        activity_id=activity_id, user_id=user_id, request_id=request_id
    )
    await _run_consumer_once(
        activity_id=activity_id, user_id=user_id, request_id=request_id
    )

    order_count, ledger_count, db_sold = await _fetch_confirmation_state(
        activity_id=activity_id,
        request_id=request_id,
    )
    assert order_count == 1
    assert ledger_count == 1
    assert db_sold == 1

    status = await _fetch_result_code(activity_id=activity_id, request_id=request_id)
    assert status == "SUCCESS"


async def _run_compensation_rollback_case() -> None:
    activity_id = await _prepare_activity()
    request_id = f"req-compensate-{uuid4().hex}"

    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.set(stock_key(activity_id), 0)
        await redis_client.set(result_key(activity_id, request_id), "PENDING")

        result = await reconcile_once(
            redis_client=redis_client,
            activity_id=activity_id,
            request_id=request_id,
        )
        assert result == "FAILED"

        restored_stock = await redis_client.get(stock_key(activity_id))
        assert restored_stock == "10"

        result_status = await redis_client.get(result_key(activity_id, request_id))
        assert result_status == "FAILED"
    finally:
        await redis_client.delete(stock_key(activity_id))
        await redis_client.delete(result_key(activity_id, request_id))
        await redis_client.aclose()

    order_count, ledger_count = await _fetch_compensation_state(
        activity_id=activity_id,
        request_id=request_id,
    )
    assert order_count == 0
    assert ledger_count == 1


async def _prepare_activity() -> int:
    now = datetime.datetime.now(datetime.UTC)
    async with SessionMaker() as session:
        activity = SeckillActivity(
            sku_id=1,
            start_at=now,
            end_at=now + datetime.timedelta(minutes=10),
            status="online",
            total_stock=10,
            db_sold=0,
        )
        session.add(activity)
        await session.commit()
        return activity.id


async def _run_consumer_once(activity_id: int, user_id: int, request_id: str) -> None:
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.xadd(
            SECKILL_STREAM_KEY,
            {
                "activity_id": str(activity_id),
                "user_id": str(user_id),
                "request_id": request_id,
            },
        )
        await consume_once(redis_client=redis_client)
    finally:
        await redis_client.delete(SECKILL_STREAM_KEY)
        await redis_client.aclose()


async def _fetch_confirmation_state(
    activity_id: int, request_id: str
) -> tuple[int, int, int]:
    async with SessionMaker() as session:
        order_count = len(
            (
                await session.execute(
                    select(SeckillOrder).where(
                        SeckillOrder.activity_id == activity_id,
                        SeckillOrder.request_id == request_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        ledger_count = len(
            (
                await session.execute(
                    select(SeckillStockLedger).where(
                        SeckillStockLedger.activity_id == activity_id,
                        SeckillStockLedger.delta == -1,
                        SeckillStockLedger.reason == "confirm_order",
                        SeckillStockLedger.biz_id == request_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        activity = await session.get(SeckillActivity, activity_id)
        if activity is None:
            raise AssertionError("seckill activity should exist")
        return order_count, ledger_count, activity.db_sold


async def _fetch_result_code(activity_id: int, request_id: str) -> str | None:
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        return await redis_client.get(result_key(activity_id, request_id))
    finally:
        await redis_client.delete(result_key(activity_id, request_id))
        await redis_client.aclose()


async def _fetch_compensation_state(
    activity_id: int, request_id: str
) -> tuple[int, int]:
    async with SessionMaker() as session:
        order_count = len(
            (
                await session.execute(
                    select(SeckillOrder).where(
                        SeckillOrder.activity_id == activity_id,
                        SeckillOrder.request_id == request_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        ledger_count = len(
            (
                await session.execute(
                    select(SeckillStockLedger).where(
                        SeckillStockLedger.activity_id == activity_id,
                        SeckillStockLedger.delta == 1,
                        SeckillStockLedger.reason == "compensate_rollback",
                        SeckillStockLedger.biz_id == request_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        return order_count, ledger_count
