from __future__ import annotations

import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orders.core.db.models import (
    SeckillActivity,
    SeckillOrder,
    SeckillRequestState,
    SeckillStockLedger,
)
from orders.seckill.exceptions import (
    SeckillActivityNotFoundError,
    SeckillDbStockExhaustedError,
)


def _naive_utc_now() -> datetime.datetime:
    """Match MySQL TIMESTAMP values returned without tzinfo."""
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _match_timestamp_reference(
    value: datetime.datetime | None,
) -> datetime.datetime:
    if value is None or value.tzinfo is None:
        return _naive_utc_now()
    return datetime.datetime.now(datetime.UTC)


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

    activity_stmt = (
        select(SeckillActivity)
        .where(SeckillActivity.id == activity_id)
        .with_for_update()
    )
    activity = await session.scalar(activity_stmt)
    if activity is None:
        raise SeckillActivityNotFoundError(f"seckill activity not found: {activity_id}")
    if activity.db_sold >= activity.total_stock:
        raise SeckillDbStockExhaustedError(
            f"seckill activity stock exhausted in db: {activity_id}"
        )

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


async def get_activity_stock_snapshot(
    session: AsyncSession,
    activity_id: int,
) -> tuple[int, int] | None:
    stmt = select(SeckillActivity.total_stock, SeckillActivity.db_sold).where(
        SeckillActivity.id == activity_id
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        return None
    total_stock, db_sold = row
    return int(total_stock), int(db_sold)


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


async def acquire_processing_lease(
    session: AsyncSession,
    activity_id: int,
    request_id: str,
    processor_id: str,
    lease_seconds: int,
) -> tuple[str, int]:
    state_stmt = (
        select(SeckillRequestState)
        .where(
            SeckillRequestState.activity_id == activity_id,
            SeckillRequestState.request_id == request_id,
        )
        .with_for_update()
    )
    state = await session.scalar(state_stmt)
    now = _match_timestamp_reference(state.lease_until if state is not None else None)
    lease_until = now + datetime.timedelta(seconds=lease_seconds)

    if state is None:
        state = SeckillRequestState(
            activity_id=activity_id,
            request_id=request_id,
            status="PROCESSING",
            retry_count=1,
            last_error=None,
            processor_id=processor_id,
            lease_until=lease_until,
        )
        session.add(state)
        await session.flush()
        return "ACQUIRED", state.retry_count

    if state.status in {"SUCCESS", "FAILED_FINAL"}:
        return "TERMINAL", state.retry_count

    if (
        state.status == "PROCESSING"
        and state.processor_id != processor_id
        and state.lease_until is not None
        and state.lease_until > now
    ):
        return "LEASED_BY_OTHER", state.retry_count

    state.retry_count += 1
    state.status = "PROCESSING"
    state.last_error = None
    state.processor_id = processor_id
    state.lease_until = lease_until
    await session.flush()
    return "ACQUIRED", state.retry_count


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
        state.processor_id = None
        state.lease_until = None
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
        state.processor_id = None
        state.lease_until = None
    await session.flush()


async def mark_retryable_failure(
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
            status="RECEIVED",
            retry_count=1,
            last_error=last_error[:255],
            processor_id=None,
            lease_until=None,
        )
        session.add(state)
    else:
        state.status = "RECEIVED"
        state.last_error = last_error[:255]
        state.processor_id = None
        state.lease_until = None
    await session.flush()
