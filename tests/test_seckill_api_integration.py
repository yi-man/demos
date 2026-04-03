from __future__ import annotations

import datetime

import redis
from fastapi.testclient import TestClient
from sqlalchemy import delete

from orders.core.db.models import SeckillActivity, SeckillOrder, SeckillRequestState, SeckillStockLedger
from orders.core.db.session import SessionMaker
from orders.core.settings import settings
from orders.main import app
from orders.seckill.consumer import SECKILL_STREAM_KEY
from orders.seckill.keys import req_key, result_key, stock_key


def test_attempt_then_result_pending() -> None:
    activity_id = _create_activity(
        status="online",
        start_offset=datetime.timedelta(minutes=-1),
        end_offset=datetime.timedelta(minutes=10),
    )
    request_id = "req-100"
    user_id = 1
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    keys_to_cleanup = [
        stock_key(activity_id),
        req_key(activity_id, request_id),
        result_key(activity_id, request_id),
    ]
    client.delete(*keys_to_cleanup)
    client.delete(SECKILL_STREAM_KEY)
    client.set(stock_key(activity_id), 1)

    try:
        with TestClient(app) as test_client:
            attempt_resp = test_client.post(
                f"/seckill/{activity_id}/attempt",
                json={"user_id": user_id, "request_id": request_id},
            )
            assert attempt_resp.status_code == 200
            assert attempt_resp.json()["code"] == "ACCEPTED"

            result_resp = test_client.get(f"/seckill/{activity_id}/result/{request_id}")
            assert result_resp.status_code == 200
            assert result_resp.json()["code"] == "PENDING"
    finally:
        client.delete(*keys_to_cleanup)
        client.delete(SECKILL_STREAM_KEY)
        _cleanup_activity(activity_id)


def test_attempt_rejects_activity_not_started() -> None:
    activity_id = _create_activity(
        status="online",
        start_offset=datetime.timedelta(minutes=5),
        end_offset=datetime.timedelta(minutes=10),
    )
    request_id = "req-not-started"
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        with TestClient(app) as test_client:
            response = test_client.post(
                f"/seckill/{activity_id}/attempt",
                json={"user_id": 1, "request_id": request_id},
            )
        assert response.status_code == 409
        assert response.json()["detail"] == "seckill activity has not started"
        assert client.exists(req_key(activity_id, request_id)) == 0
        assert client.get(result_key(activity_id, request_id)) is None
        assert client.xlen(SECKILL_STREAM_KEY) == 0
    finally:
        client.delete(SECKILL_STREAM_KEY)
        _cleanup_activity(activity_id)


def test_attempt_rejects_activity_not_online() -> None:
    activity_id = _create_activity(
        status="closed",
        start_offset=datetime.timedelta(minutes=-1),
        end_offset=datetime.timedelta(minutes=10),
    )
    request_id = "req-closed"
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        with TestClient(app) as test_client:
            response = test_client.post(
                f"/seckill/{activity_id}/attempt",
                json={"user_id": 1, "request_id": request_id},
            )
        assert response.status_code == 409
        assert response.json()["detail"] == "seckill activity is not online"
        assert client.exists(req_key(activity_id, request_id)) == 0
        assert client.get(result_key(activity_id, request_id)) is None
        assert client.xlen(SECKILL_STREAM_KEY) == 0
    finally:
        client.delete(SECKILL_STREAM_KEY)
        _cleanup_activity(activity_id)


def _create_activity(
    *,
    status: str,
    start_offset: datetime.timedelta,
    end_offset: datetime.timedelta,
) -> int:
    return __import__("asyncio").run(
        _create_activity_async(
            status=status,
            start_offset=start_offset,
            end_offset=end_offset,
        )
    )


async def _create_activity_async(
    *,
    status: str,
    start_offset: datetime.timedelta,
    end_offset: datetime.timedelta,
) -> int:
    now = datetime.datetime.now(datetime.UTC)
    async with SessionMaker() as session:
        async with session.begin():
            activity = SeckillActivity(
                sku_id=10001,
                start_at=now + start_offset,
                end_at=now + end_offset,
                status=status,
                total_stock=1,
                db_sold=0,
            )
            session.add(activity)
            await session.flush()
            return int(activity.id)


def _cleanup_activity(activity_id: int) -> None:
    __import__("asyncio").run(_cleanup_activity_async(activity_id))


async def _cleanup_activity_async(activity_id: int) -> None:
    async with SessionMaker() as session:
        async with session.begin():
            await session.execute(
                delete(SeckillOrder).where(SeckillOrder.activity_id == activity_id)
            )
            await session.execute(
                delete(SeckillRequestState).where(
                    SeckillRequestState.activity_id == activity_id
                )
            )
            await session.execute(
                delete(SeckillStockLedger).where(
                    SeckillStockLedger.activity_id == activity_id
                )
            )
            await session.execute(
                delete(SeckillActivity).where(SeckillActivity.id == activity_id)
            )
