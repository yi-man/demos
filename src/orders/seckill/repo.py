from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orders.core.db.models import (
    SeckillActivity,
    SeckillOrder,
    SeckillRequestState,
    SeckillStockLedger,
)


async def confirm_order_once(
    session: AsyncSession,
    activity_id: int,
    user_id: int,
    request_id: str,
) -> bool:
    existing_stmt = select(SeckillOrder.id).where(
        SeckillOrder.activity_id == activity_id,
        SeckillOrder.request_id == request_id,
    )
    existing_order_id = await session.scalar(existing_stmt)
    if existing_order_id is not None:
        return False

    activity = await session.get(SeckillActivity, activity_id)
    if activity is None:
        raise ValueError(f"seckill activity not found: {activity_id}")

    order = SeckillOrder(
        activity_id=activity_id,
        user_id=user_id,
        request_id=request_id,
        order_no=f"SK{uuid4().hex[:30]}",
        status="created",
    )
    session.add(order)
    session.add(
        SeckillStockLedger(
            activity_id=activity_id,
            delta=-1,
            reason="confirm_order",
            biz_id=request_id,
        )
    )
    activity.db_sold += 1
    await session.flush()
    return True


async def has_order(
    session: AsyncSession,
    activity_id: int,
    request_id: str,
) -> bool:
    existing_stmt = select(SeckillOrder.id).where(
        SeckillOrder.activity_id == activity_id,
        SeckillOrder.request_id == request_id,
    )
    return await session.scalar(existing_stmt) is not None


async def has_activity(
    session: AsyncSession,
    activity_id: int,
) -> bool:
    return await session.get(SeckillActivity, activity_id) is not None


async def add_compensation_ledger_once(
    session: AsyncSession,
    activity_id: int,
    request_id: str,
) -> bool:
    existing_stmt = select(SeckillStockLedger.id).where(
        SeckillStockLedger.activity_id == activity_id,
        SeckillStockLedger.delta == 1,
        SeckillStockLedger.reason == "compensate_rollback",
        SeckillStockLedger.biz_id == request_id,
    )
    existing_ledger_id = await session.scalar(existing_stmt)
    if existing_ledger_id is not None:
        return False

    session.add(
        SeckillStockLedger(
            activity_id=activity_id,
            delta=1,
            reason="compensate_rollback",
            biz_id=request_id,
        )
    )
    await session.flush()
    return True


async def upsert_processing_state(
    session: AsyncSession,
    activity_id: int,
    request_id: str,
) -> int:
    state_stmt = select(SeckillRequestState).where(
        SeckillRequestState.activity_id == activity_id,
        SeckillRequestState.request_id == request_id,
    )
    state = await session.scalar(state_stmt)
    if state is None:
        state = SeckillRequestState(
            activity_id=activity_id,
            request_id=request_id,
            status="PROCESSING",
            retry_count=1,
            last_error=None,
        )
        session.add(state)
        await session.flush()
        return state.retry_count

    state.retry_count += 1
    state.status = "PROCESSING"
    state.last_error = None
    await session.flush()
    return state.retry_count


async def mark_success(
    session: AsyncSession,
    activity_id: int,
    request_id: str,
) -> None:
    state_stmt = select(SeckillRequestState).where(
        SeckillRequestState.activity_id == activity_id,
        SeckillRequestState.request_id == request_id,
    )
    state = await session.scalar(state_stmt)
    if state is None:
        state = SeckillRequestState(
            activity_id=activity_id,
            request_id=request_id,
            status="SUCCESS",
            retry_count=1,
            last_error=None,
        )
        session.add(state)
    else:
        state.status = "SUCCESS"
        state.last_error = None
    await session.flush()


async def mark_failed_final(
    session: AsyncSession,
    activity_id: int,
    request_id: str,
    last_error: str,
) -> None:
    state_stmt = select(SeckillRequestState).where(
        SeckillRequestState.activity_id == activity_id,
        SeckillRequestState.request_id == request_id,
    )
    state = await session.scalar(state_stmt)
    if state is None:
        state = SeckillRequestState(
            activity_id=activity_id,
            request_id=request_id,
            status="FAILED_FINAL",
            retry_count=1,
            last_error=last_error[:255],
        )
        session.add(state)
    else:
        state.status = "FAILED_FINAL"
        state.last_error = last_error[:255]
    await session.flush()
