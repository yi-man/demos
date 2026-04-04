from __future__ import annotations

import asyncio
import datetime
import uuid

import redis
from fastapi.testclient import TestClient
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from orders.core.db.alembic_utils import build_mysql_sync_url
from orders.core.db.models import (
    SeckillActivity,
    SeckillOrder,
    SeckillRequestState,
    SeckillStockLedger,
)
from orders.core.db.session import SessionMaker
from orders.core.settings import settings
from orders.main import app
from orders.seckill.compensation import reconcile_once
from orders.seckill.consumer import (
    SECKILL_STREAM_GROUP,
    SECKILL_STREAM_KEY,
    consume_once,
    ensure_consumer_group,
)
from orders.seckill.keys import (
    finalized_key,
    inflight_key,
    req_key,
    result_key,
    stock_key,
)


def test_attempt_rejects_activity_ended() -> None:
    activity_id = _create_activity(
        status="online",
        start_offset=datetime.timedelta(minutes=-10),
        end_offset=datetime.timedelta(minutes=-1),
        total_stock=1,
    )
    request_id = f"ended-{uuid.uuid4().hex}"
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        client.delete(SECKILL_STREAM_KEY)
        with TestClient(app) as test_client:
            response = test_client.post(
                f"/seckill/{activity_id}/attempt",
                json={"user_id": 1, "request_id": request_id},
            )
        assert response.status_code == 409
        assert response.json()["detail"] == "seckill activity has ended"
        assert client.exists(req_key(activity_id, request_id)) == 0
        assert client.get(result_key(activity_id, request_id)) is None
        assert client.xlen(SECKILL_STREAM_KEY) == 0
    finally:
        client.delete(SECKILL_STREAM_KEY)
        _cleanup_activity(activity_id)


def test_consumer_marks_failed_when_db_stock_is_exhausted() -> None:
    asyncio.run(_run_db_stock_exhausted_case())


def test_consumer_handles_missing_stream_during_autoclaim() -> None:
    asyncio.run(_run_missing_stream_autoclaim_case())


def test_reconcile_sets_success_when_db_order_exists_but_result_is_missing() -> None:
    asyncio.run(_run_reconcile_success_backfill_case())


def test_failed_reconcile_preserves_other_inflight_reservations() -> None:
    asyncio.run(_run_failed_reconcile_preserves_other_inflight_case())


async def _run_db_stock_exhausted_case() -> None:
    activity_id = _create_activity(
        status="online",
        start_offset=datetime.timedelta(minutes=-1),
        end_offset=datetime.timedelta(minutes=10),
        total_stock=1,
        db_sold=1,
    )
    request_id = f"db-exhausted-{uuid.uuid4().hex}"
    redis_client = AsyncRedis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.delete(SECKILL_STREAM_KEY)
        await redis_client.set(stock_key(activity_id), 1)

        accepted = await redis_client.eval(
            """
            local ttl = ARGV[1]
            if redis.call("EXISTS", KEYS[2]) == 1 then
                return "DUPLICATE"
            end
            local stock = tonumber(redis.call("GET", KEYS[1]) or "0")
            if stock <= 0 then
                return "SOLD_OUT"
            end
            redis.call("DECR", KEYS[1])
            redis.call("INCR", KEYS[5])
            redis.call("SET", KEYS[2], "1", "EX", ttl)
            redis.call("SET", KEYS[3], "PENDING", "EX", ttl)
            redis.call(
                "XADD",
                KEYS[4],
                "*",
                "activity_id",
                ARGV[2],
                "user_id",
                ARGV[3],
                "request_id",
                ARGV[4]
            )
            return "ACCEPTED"
            """,
            5,
            stock_key(activity_id),
            req_key(activity_id, request_id),
            result_key(activity_id, request_id),
            SECKILL_STREAM_KEY,
            inflight_key(activity_id),
            "300",
            str(activity_id),
            "42",
            request_id,
        )
        assert accepted == "ACCEPTED"

        ok = await consume_once(redis_client=redis_client, max_retries=1)
        assert ok is True

        result = await redis_client.get(result_key(activity_id, request_id))
        stock = await redis_client.get(stock_key(activity_id))
        inflight = await redis_client.get(inflight_key(activity_id))
        assert result == "FAILED"
        assert stock == "0"
        assert inflight == "0"

        async with SessionMaker() as session:
            state = await session.scalar(
                select(SeckillRequestState).where(
                    SeckillRequestState.activity_id == activity_id,
                    SeckillRequestState.request_id == request_id,
                )
            )
            assert state is not None
            assert state.status == "FAILED_FINAL"
            assert "stock exhausted in db" in (state.last_error or "")

            order = await session.scalar(
                select(SeckillOrder).where(
                    SeckillOrder.activity_id == activity_id,
                    SeckillOrder.request_id == request_id,
                )
            )
            assert order is None
    finally:
        await redis_client.delete(SECKILL_STREAM_KEY)
        await redis_client.delete(inflight_key(activity_id))
        await redis_client.delete(finalized_key(activity_id, request_id))
        await redis_client.delete(stock_key(activity_id))
        await redis_client.delete(req_key(activity_id, request_id))
        await redis_client.delete(result_key(activity_id, request_id))
        await redis_client.aclose()
        _cleanup_activity(activity_id)


async def _run_missing_stream_autoclaim_case() -> None:
    redis_client = AsyncRedis.from_url(settings.redis_url, decode_responses=True)
    stream_key = f"{SECKILL_STREAM_KEY}:missing:{uuid.uuid4().hex}"
    group_name = f"{SECKILL_STREAM_GROUP}-missing"
    try:
        await redis_client.delete(stream_key)
        await ensure_consumer_group(
            redis_client,
            stream_key=stream_key,
            group_name=group_name,
        )

        # Block a consumer on an empty stream, then delete the key to trigger
        # the Redis UNBLOCKED/missing-stream response path.
        blocked = asyncio.create_task(
            consume_once(
                redis_client=redis_client,
                stream_key=stream_key,
                group_name=group_name,
                consumer_name="missing-stream-consumer",
                lease_seconds=1,
            )
        )
        await asyncio.sleep(0.1)
        await redis_client.delete(stream_key)

        result = await blocked
        assert result is False
    finally:
        await redis_client.delete(stream_key)
        await redis_client.aclose()


async def _run_reconcile_success_backfill_case() -> None:
    activity_id = _create_activity(
        status="online",
        start_offset=datetime.timedelta(minutes=-1),
        end_offset=datetime.timedelta(minutes=10),
        total_stock=2,
    )
    request_id = f"reconcile-success-{uuid.uuid4().hex}"
    redis_client = AsyncRedis.from_url(settings.redis_url, decode_responses=True)
    try:
        _insert_confirmed_order(
            activity_id=activity_id,
            request_id=request_id,
            user_id=99,
        )
        await redis_client.set(inflight_key(activity_id), 1)
        await redis_client.delete(result_key(activity_id, request_id))

        result = await reconcile_once(
            redis_client=redis_client,
            activity_id=activity_id,
            request_id=request_id,
        )
        assert result == "SUCCESS"
        assert await redis_client.get(result_key(activity_id, request_id)) == "SUCCESS"
        assert await redis_client.get(inflight_key(activity_id)) == "0"
        assert await redis_client.get(stock_key(activity_id)) == "1"
    finally:
        await redis_client.delete(stock_key(activity_id))
        await redis_client.delete(inflight_key(activity_id))
        await redis_client.delete(finalized_key(activity_id, request_id))
        await redis_client.delete(result_key(activity_id, request_id))
        await redis_client.aclose()
        _cleanup_activity(activity_id)


async def _run_failed_reconcile_preserves_other_inflight_case() -> None:
    activity_id = _create_activity(
        status="online",
        start_offset=datetime.timedelta(minutes=-1),
        end_offset=datetime.timedelta(minutes=10),
        total_stock=3,
    )
    failed_request_id = f"reconcile-failed-{uuid.uuid4().hex}"
    other_request_id = f"reconcile-other-{uuid.uuid4().hex}"
    redis_client = AsyncRedis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.set(stock_key(activity_id), 0)
        await redis_client.set(inflight_key(activity_id), 2)
        await redis_client.set(result_key(activity_id, failed_request_id), "PENDING")
        await redis_client.set(result_key(activity_id, other_request_id), "PENDING")

        result = await reconcile_once(
            redis_client=redis_client,
            activity_id=activity_id,
            request_id=failed_request_id,
        )
        assert result == "FAILED"
        assert (
            await redis_client.get(result_key(activity_id, failed_request_id))
            == "FAILED"
        )
        assert await redis_client.get(stock_key(activity_id)) == "2"
        assert await redis_client.get(inflight_key(activity_id)) == "1"
        assert (
            await redis_client.get(finalized_key(activity_id, failed_request_id))
            == "FAILED"
        )
        assert (
            await redis_client.get(result_key(activity_id, other_request_id))
            == "PENDING"
        )
    finally:
        await redis_client.delete(finalized_key(activity_id, failed_request_id))
        await redis_client.delete(inflight_key(activity_id))
        await redis_client.delete(stock_key(activity_id))
        await redis_client.delete(result_key(activity_id, failed_request_id))
        await redis_client.delete(result_key(activity_id, other_request_id))
        await redis_client.aclose()
        _cleanup_activity(activity_id)


def _create_activity(
    *,
    status: str,
    start_offset: datetime.timedelta,
    end_offset: datetime.timedelta,
    total_stock: int,
    db_sold: int = 0,
) -> int:
    now = datetime.datetime.now(datetime.UTC)
    with Session(_sync_engine()) as session:
        activity = SeckillActivity(
            sku_id=20001,
            start_at=now + start_offset,
            end_at=now + end_offset,
            status=status,
            total_stock=total_stock,
            db_sold=db_sold,
        )
        session.add(activity)
        session.commit()
        session.refresh(activity)
        return int(activity.id)


def _insert_confirmed_order(activity_id: int, request_id: str, user_id: int) -> None:
    with Session(_sync_engine()) as session:
        activity = session.get(SeckillActivity, activity_id)
        if activity is None:
            raise AssertionError("activity should exist")

        session.add(
            SeckillOrder(
                activity_id=activity_id,
                user_id=user_id,
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
        activity.db_sold += 1
        session.commit()


def _cleanup_activity(activity_id: int) -> None:
    with Session(_sync_engine()) as session:
        session.execute(
            delete(SeckillOrder).where(SeckillOrder.activity_id == activity_id)
        )
        session.execute(
            delete(SeckillRequestState).where(
                SeckillRequestState.activity_id == activity_id
            )
        )
        session.execute(
            delete(SeckillStockLedger).where(
                SeckillStockLedger.activity_id == activity_id
            )
        )
        session.execute(
            delete(SeckillActivity).where(SeckillActivity.id == activity_id)
        )
        session.commit()


def _sync_engine():
    return create_engine(build_mysql_sync_url(), pool_pre_ping=True)
