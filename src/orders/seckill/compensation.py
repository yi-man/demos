from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orders.core.db.models import SeckillActivity
from orders.core.db.session import SessionMaker
from orders.seckill.keys import result_key, stock_key
from orders.seckill.repo import add_compensation_ledger_once, has_activity, has_order

FAILED_TTL_SECONDS = 300
SUCCESS_TTL_SECONDS = 300


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
                await redis_client.set(
                    result_key(activity_id, request_id),
                    "SUCCESS",
                    ex=SUCCESS_TTL_SECONDS,
                )
                return "SUCCESS"

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
                if target_stock is not None:
                    await redis_client.set(stock_key(activity_id), target_stock)
            elif not activity_exists:
                # Activity may be removed or not yet materialized.
                # Still release reservation in Redis.
                await redis_client.incr(stock_key(activity_id))
            await redis_client.set(
                result_key(activity_id, request_id),
                "FAILED",
                ex=FAILED_TTL_SECONDS,
            )
            return "FAILED"
