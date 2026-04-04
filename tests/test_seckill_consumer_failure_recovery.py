from __future__ import annotations

import asyncio
import uuid

import pytest
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import delete, select

from orders.core.db.models import SeckillRequestState, SeckillStockLedger
from orders.core.db.session import SessionMaker
from orders.core.settings import settings
from orders.seckill.consumer import SECKILL_STREAM_KEY, consume_once
from orders.seckill.keys import (
    finalized_key,
    inflight_key,
    req_key,
    result_key,
    stock_key,
)
from orders.seckill.worker import run_consumer_loop


def test_consume_once_activity_not_found_becomes_failed_final() -> None:
    asyncio.run(_run_activity_missing_case())


async def _run_activity_missing_case() -> None:
    activity_id = 987654321
    request_id = f"missing-{uuid.uuid4().hex}"

    redis_client = AsyncRedis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.delete(SECKILL_STREAM_KEY)
        await redis_client.delete(stock_key(activity_id))
        await redis_client.delete(req_key(activity_id, request_id))
        await redis_client.delete(result_key(activity_id, request_id))

        # Simulate Lua pre-deduct already happened.
        await redis_client.set(stock_key(activity_id), 0)
        await redis_client.set(inflight_key(activity_id), 1)
        await redis_client.set(result_key(activity_id, request_id), "PENDING")
        await redis_client.xadd(
            SECKILL_STREAM_KEY,
            {
                "activity_id": str(activity_id),
                "user_id": "100",
                "request_id": request_id,
            },
        )

        ok = await consume_once(redis_client=redis_client, max_retries=1)
        assert ok is True

        current_result = await redis_client.get(result_key(activity_id, request_id))
        assert current_result == "FAILED"
        current_stock = await redis_client.get(stock_key(activity_id))
        assert current_stock is None
        inflight = await redis_client.get(inflight_key(activity_id))
        assert inflight == "0"
        assert (
            await redis_client.get(finalized_key(activity_id, request_id))
            == "FAILED"
        )
        stream_len = await redis_client.xlen(SECKILL_STREAM_KEY)
        assert stream_len == 0

        async with SessionMaker() as session:
            state = await session.scalar(
                select(SeckillRequestState).where(
                    SeckillRequestState.activity_id == activity_id,
                    SeckillRequestState.request_id == request_id,
                )
            )
            assert state is not None
            assert state.status == "FAILED_FINAL"
            assert state.retry_count == 1
            assert state.last_error is not None
            assert "activity not found" in state.last_error

            ledger_rows = await session.execute(
                select(SeckillStockLedger).where(
                    SeckillStockLedger.activity_id == activity_id,
                    SeckillStockLedger.biz_id == request_id,
                    SeckillStockLedger.reason == "compensate_rollback",
                )
            )
            # Activity does not exist, FK blocks compensation ledger.
            assert len(ledger_rows.scalars().all()) == 0
    finally:
        async with SessionMaker() as session:
            async with session.begin():
                await session.execute(
                    delete(SeckillRequestState).where(
                        SeckillRequestState.activity_id == activity_id,
                        SeckillRequestState.request_id == request_id,
                    )
                )
        await redis_client.delete(SECKILL_STREAM_KEY)
        await redis_client.delete(stock_key(activity_id))
        await redis_client.delete(inflight_key(activity_id))
        await redis_client.delete(finalized_key(activity_id, request_id))
        await redis_client.delete(req_key(activity_id, request_id))
        await redis_client.delete(result_key(activity_id, request_id))
        await redis_client.aclose()


def test_worker_loop_survives_consume_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_run_worker_guard_case(monkeypatch))


async def _run_worker_guard_case(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyRedis:
        pass

    call_count = {"n": 0}

    async def _broken_consume_once(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        call_count["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "orders.seckill.worker.consume_once",
        _broken_consume_once,
    )

    processed = await run_consumer_loop(
        DummyRedis(),  # type: ignore[arg-type]
        consumer_name="test-worker-failure",
        max_rounds=1,
        sleep_when_empty_s=0.01,
    )
    assert processed == 0
    assert call_count["n"] == 1
