from __future__ import annotations

import asyncio
import datetime
import uuid

from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import delete, func, select

from orders.core.db.models import (
    SeckillActivity,
    SeckillOrder,
    SeckillRequestState,
    SeckillStockLedger,
)
from orders.core.db.session import SessionMaker
from orders.core.settings import settings
from orders.seckill.consumer import (
    SECKILL_STREAM_GROUP,
    SECKILL_STREAM_KEY,
    consume_once,
    ensure_consumer_group,
)
from orders.seckill.keys import (
    finalized_key,
    inflight_key,
    result_key,
)


def test_consume_once_keeps_message_when_lease_belongs_to_other_worker() -> None:
    asyncio.run(_run_lease_conflict_case())


async def _run_lease_conflict_case() -> None:
    now = datetime.datetime.now(datetime.UTC)
    activity_id: int | None = None
    request_id = f"lease-{uuid.uuid4().hex}"
    redis_client = AsyncRedis.from_url(settings.redis_url, decode_responses=True)

    try:
        async with SessionMaker() as session:
            async with session.begin():
                activity = SeckillActivity(
                    sku_id=45678,
                    start_at=now - datetime.timedelta(minutes=1),
                    end_at=now + datetime.timedelta(minutes=10),
                    status="online",
                    total_stock=1,
                    db_sold=0,
                )
                session.add(activity)
                await session.flush()
                activity_id = int(activity.id)

                session.add(
                    SeckillRequestState(
                        activity_id=activity_id,
                        request_id=request_id,
                        status="PROCESSING",
                        retry_count=1,
                        last_error=None,
                        processor_id="worker-a",
                        lease_until=now + datetime.timedelta(seconds=60),
                    )
                )

        assert activity_id is not None

        await redis_client.delete(SECKILL_STREAM_KEY)
        await ensure_consumer_group(redis_client)
        await redis_client.xadd(
            SECKILL_STREAM_KEY,
            {
                "activity_id": str(activity_id),
                "user_id": "7",
                "request_id": request_id,
            },
        )

        outcome = await consume_once(
            redis_client=redis_client,
            consumer_name="worker-b",
            lease_seconds=30,
        )
        assert outcome is False

        pending_summary = await redis_client.xpending(
            SECKILL_STREAM_KEY,
            SECKILL_STREAM_GROUP,
        )
        assert pending_summary["pending"] == 1

        stream_len = await redis_client.xlen(SECKILL_STREAM_KEY)
        assert stream_len == 1

        async with SessionMaker() as session:
            state = await session.scalar(
                select(SeckillRequestState).where(
                    SeckillRequestState.activity_id == activity_id,
                    SeckillRequestState.request_id == request_id,
                )
            )
            assert state is not None
            assert state.processor_id == "worker-a"
            assert state.status == "PROCESSING"
    finally:
        if activity_id is not None:
            async with SessionMaker() as session:
                async with session.begin():
                    await session.execute(
                        delete(SeckillRequestState).where(
                            SeckillRequestState.activity_id == activity_id
                        )
                    )
                    await session.execute(
                        delete(SeckillActivity).where(SeckillActivity.id == activity_id)
                    )
        await redis_client.delete(SECKILL_STREAM_KEY)
        await redis_client.aclose()


def test_consume_once_drops_redelivered_terminal_message() -> None:
    asyncio.run(_run_terminal_redelivery_case())


async def _run_terminal_redelivery_case() -> None:
    now = datetime.datetime.now(datetime.UTC)
    activity_id: int | None = None
    request_id = f"terminal-{uuid.uuid4().hex}"
    redis_client = AsyncRedis.from_url(settings.redis_url, decode_responses=True)

    try:
        async with SessionMaker() as session:
            async with session.begin():
                activity = SeckillActivity(
                    sku_id=56789,
                    start_at=now - datetime.timedelta(minutes=1),
                    end_at=now + datetime.timedelta(minutes=10),
                    status="online",
                    total_stock=1,
                    db_sold=0,
                )
                session.add(activity)
                await session.flush()
                activity_id = int(activity.id)

                session.add(
                    SeckillRequestState(
                        activity_id=activity_id,
                        request_id=request_id,
                        status="FAILED_FINAL",
                        retry_count=3,
                        last_error="boom",
                        processor_id=None,
                        lease_until=None,
                    )
                )

        assert activity_id is not None

        await redis_client.delete(SECKILL_STREAM_KEY)
        await redis_client.set(inflight_key(activity_id), 1)
        await redis_client.delete(result_key(activity_id, request_id))
        await redis_client.delete(finalized_key(activity_id, request_id))
        await ensure_consumer_group(redis_client)
        await redis_client.xadd(
            SECKILL_STREAM_KEY,
            {
                "activity_id": str(activity_id),
                "user_id": "9",
                "request_id": request_id,
            },
        )

        outcome = await consume_once(
            redis_client=redis_client,
            consumer_name="worker-redelivery",
            lease_seconds=30,
        )
        assert outcome is True

        stream_len = await redis_client.xlen(SECKILL_STREAM_KEY)
        assert stream_len == 0
        assert await redis_client.get(result_key(activity_id, request_id)) == "FAILED"
        assert (
            await redis_client.get(finalized_key(activity_id, request_id)) == "FAILED"
        )
        assert await redis_client.get(inflight_key(activity_id)) == "0"

        async with SessionMaker() as session:
            state = await session.scalar(
                select(SeckillRequestState).where(
                    SeckillRequestState.activity_id == activity_id,
                    SeckillRequestState.request_id == request_id,
                )
            )
            assert state is not None
            assert state.status == "FAILED_FINAL"
            assert state.retry_count == 3

            order_count = await session.scalar(
                select(func.count())
                .select_from(SeckillOrder)
                .where(
                    SeckillOrder.activity_id == activity_id,
                    SeckillOrder.request_id == request_id,
                )
            )
            assert int(order_count or 0) == 0
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
                        delete(SeckillRequestState).where(
                            SeckillRequestState.activity_id == activity_id
                        )
                    )
                    await session.execute(
                        delete(SeckillActivity).where(SeckillActivity.id == activity_id)
                    )
        await redis_client.delete(SECKILL_STREAM_KEY)
        if activity_id is not None:
            await redis_client.delete(inflight_key(activity_id))
        await redis_client.delete(finalized_key(activity_id, request_id))
        await redis_client.delete(result_key(activity_id, request_id))
        await redis_client.aclose()


def test_consume_once_recovers_redelivered_terminal_success_message() -> None:
    asyncio.run(_run_terminal_success_redelivery_case())


async def _run_terminal_success_redelivery_case() -> None:
    now = datetime.datetime.now(datetime.UTC)
    activity_id: int | None = None
    request_id = f"terminal-success-{uuid.uuid4().hex}"
    redis_client = AsyncRedis.from_url(settings.redis_url, decode_responses=True)

    try:
        async with SessionMaker() as session:
            async with session.begin():
                activity = SeckillActivity(
                    sku_id=67890,
                    start_at=now - datetime.timedelta(minutes=1),
                    end_at=now + datetime.timedelta(minutes=10),
                    status="online",
                    total_stock=2,
                    db_sold=1,
                )
                session.add(activity)
                await session.flush()
                activity_id = int(activity.id)

                session.add(
                    SeckillOrder(
                        activity_id=activity_id,
                        user_id=10,
                        request_id=request_id,
                        order_no=f"SK{uuid.uuid4().hex[:30]}",
                        status="created",
                    )
                )
                session.add(
                    SeckillStockLedger(
                        activity_id=activity_id,
                        delta=-1,
                        reason="confirm_order",
                        biz_id=request_id,
                    )
                )
                session.add(
                    SeckillRequestState(
                        activity_id=activity_id,
                        request_id=request_id,
                        status="SUCCESS",
                        retry_count=2,
                        last_error=None,
                        processor_id=None,
                        lease_until=None,
                    )
                )

        assert activity_id is not None

        await redis_client.delete(SECKILL_STREAM_KEY)
        await redis_client.set(inflight_key(activity_id), 1)
        await redis_client.delete(result_key(activity_id, request_id))
        await redis_client.delete(finalized_key(activity_id, request_id))
        await ensure_consumer_group(redis_client)
        await redis_client.xadd(
            SECKILL_STREAM_KEY,
            {
                "activity_id": str(activity_id),
                "user_id": "10",
                "request_id": request_id,
            },
        )

        outcome = await consume_once(
            redis_client=redis_client,
            consumer_name="worker-terminal-success",
            lease_seconds=30,
        )
        assert outcome is True

        assert await redis_client.xlen(SECKILL_STREAM_KEY) == 0
        assert await redis_client.get(result_key(activity_id, request_id)) == "SUCCESS"
        assert (
            await redis_client.get(finalized_key(activity_id, request_id)) == "SUCCESS"
        )
        assert await redis_client.get(inflight_key(activity_id)) == "0"
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
                        delete(SeckillRequestState).where(
                            SeckillRequestState.activity_id == activity_id
                        )
                    )
                    await session.execute(
                        delete(SeckillActivity).where(SeckillActivity.id == activity_id)
                    )
            await redis_client.delete(inflight_key(activity_id))
        await redis_client.delete(SECKILL_STREAM_KEY)
        await redis_client.delete(finalized_key(activity_id, request_id))
        await redis_client.delete(result_key(activity_id, request_id))
        await redis_client.aclose()
