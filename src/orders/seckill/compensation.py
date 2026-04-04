from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orders.core.db.models import SeckillActivity
from orders.core.db.session import SessionMaker
from orders.seckill.keys import (
    finalized_key,
    inflight_key,
    req_key,
    result_key,
    stock_key,
)
from orders.seckill.repo import add_compensation_ledger_once, has_activity, has_order

FAILED_TTL_SECONDS = 300
SUCCESS_TTL_SECONDS = 300


async def finalize_request_once(
    redis_client,
    *,
    activity_id: int,
    request_id: str,
    result: str,
    ttl_seconds: int,
    release_reservation: bool,
    stock_target_after_release: int | None = None,
) -> str:
    finalized = await redis_client.set(
        finalized_key(activity_id, request_id),
        result,
        ex=ttl_seconds,
        nx=True,
    )
    if finalized and release_reservation:
        inflight_after = await redis_client.decr(inflight_key(activity_id))
        if inflight_after < 0:
            await redis_client.set(inflight_key(activity_id), 0)
            inflight_after = 0

        if stock_target_after_release is not None:
            target_stock = max(stock_target_after_release - inflight_after, 0)
            await redis_client.set(stock_key(activity_id), target_stock)

    await redis_client.set(
        result_key(activity_id, request_id),
        result,
        ex=ttl_seconds,
    )
    return result


async def reconcile_once(
    redis_client,
    activity_id: int,
    request_id: str,
    session_maker: async_sessionmaker[AsyncSession] = SessionMaker,
) -> str:
    async with session_maker() as session:
        async with session.begin():
            order_exists = await has_order(
                session=session,
                activity_id=activity_id,
                request_id=request_id,
            )
            if order_exists:
                return await finalize_request_once(
                    redis_client,
                    activity_id=activity_id,
                    request_id=request_id,
                    result="SUCCESS",
                    ttl_seconds=SUCCESS_TTL_SECONDS,
                    release_reservation=True,
                )

            activity_exists = await has_activity(
                session=session,
                activity_id=activity_id,
            )
            ledger_added = False
            target_stock: int | None = None
            if activity_exists:
                activity = await session.scalar(
                    select(SeckillActivity)
                    .where(SeckillActivity.id == activity_id)
                    .with_for_update()
                )
                if activity is None:
                    activity_exists = False
                else:
                    target_stock = max(activity.total_stock - activity.db_sold, 0)
                ledger_added = await add_compensation_ledger_once(
                    session=session,
                    activity_id=activity_id,
                    request_id=request_id,
                )
            if ledger_added:
                return await finalize_request_once(
                    redis_client,
                    activity_id=activity_id,
                    request_id=request_id,
                    result="FAILED",
                    ttl_seconds=FAILED_TTL_SECONDS,
                    release_reservation=True,
                    stock_target_after_release=target_stock,
                )
            elif not activity_exists:
                await redis_client.delete(req_key(activity_id, request_id))
                result = await finalize_request_once(
                    redis_client,
                    activity_id=activity_id,
                    request_id=request_id,
                    result="FAILED",
                    ttl_seconds=FAILED_TTL_SECONDS,
                    release_reservation=True,
                )
                await redis_client.delete(stock_key(activity_id))
                return result
            return await finalize_request_once(
                redis_client,
                activity_id=activity_id,
                request_id=request_id,
                result="FAILED",
                ttl_seconds=FAILED_TTL_SECONDS,
                release_reservation=False,
            )
