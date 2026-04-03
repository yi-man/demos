from __future__ import annotations

import asyncio
import datetime
import uuid

from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import delete, select

from orders.core.db.models import SeckillActivity, SeckillRequestState
from orders.core.db.session import SessionMaker
from orders.core.settings import settings
from orders.seckill.consumer import (
    SECKILL_STREAM_GROUP,
    SECKILL_STREAM_KEY,
    consume_once,
    ensure_consumer_group,
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
