from __future__ import annotations

from enum import Enum

from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orders.core.db.session import SessionMaker
from orders.seckill.compensation import reconcile_once
from orders.seckill.exceptions import (
    SeckillActivityNotFoundError,
    SeckillDbStockExhaustedError,
)
from orders.seckill.keys import finalized_key, inflight_key, result_key
from orders.seckill.repo import (
    acquire_processing_lease,
    confirm_order_once,
    mark_failed_final,
    mark_retryable_failure,
    mark_success,
)

SECKILL_STREAM_KEY = "seckill:stream"
SECKILL_STREAM_GROUP = "seckill-consumer-group"
SUCCESS_TTL_SECONDS = 300
DEFAULT_MAX_RETRIES = 3
DEFAULT_LEASE_SECONDS = 30


class LeaseAcquireStatus(str, Enum):
    ACQUIRED = "ACQUIRED"
    TERMINAL = "TERMINAL"
    LEASED_BY_OTHER = "LEASED_BY_OTHER"


def _decode(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def _payload_value(payload: dict, key: str) -> str:
    value = payload.get(key)
    if value is None:
        value = payload.get(key.encode("utf-8"))
    if value is None:
        raise KeyError(f"missing payload key: {key}")
    return _decode(value)


async def ensure_consumer_group(
    redis_client,
    stream_key: str = SECKILL_STREAM_KEY,
    group_name: str = SECKILL_STREAM_GROUP,
) -> None:
    try:
        await redis_client.xgroup_create(
            name=stream_key,
            groupname=group_name,
            id="0-0",
            mkstream=True,
        )
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def _safe_xreadgroup(
    redis_client,
    *,
    group_name: str,
    consumer_name: str,
    stream_key: str,
):
    try:
        return await redis_client.xreadgroup(
            groupname=group_name,
            consumername=consumer_name,
            streams={stream_key: ">"},
            count=1,
            block=1000,
        )
    except ResponseError as exc:
        if _is_missing_stream_response(exc):
            return []
        raise


async def _safe_xautoclaim(
    redis_client,
    *,
    group_name: str,
    consumer_name: str,
    stream_key: str,
    lease_seconds: int,
):
    try:
        return await redis_client.xautoclaim(
            name=stream_key,
            groupname=group_name,
            consumername=consumer_name,
            min_idle_time=lease_seconds * 1000,
            start_id="0-0",
            count=1,
        )
    except ResponseError as exc:
        if _is_missing_stream_response(exc):
            return []
        raise


def _is_missing_stream_response(exc: ResponseError) -> bool:
    message = str(exc)
    normalized = message.lower()
    return (
        "no such key" in normalized
        or "stream key no longer exists" in normalized
    )


def _coerce_entries(records: list) -> list[tuple[str, dict]]:
    if not records:
        return []
    _, entries = records[0]
    return entries


def _coerce_autoclaim_entries(result) -> list[tuple[str, dict]]:
    if not result:
        return []
    if isinstance(result, (list, tuple)) and len(result) >= 2:
        claimed = result[1]
        if isinstance(claimed, list):
            return claimed
    return []


async def _finalize_request(
    redis_client,
    *,
    activity_id: int,
    request_id: str,
    result_code: str,
    result_ttl_seconds: int,
) -> None:
    request_finalized_key = finalized_key(activity_id, request_id)
    finalized = await redis_client.set(
        request_finalized_key,
        result_code,
        ex=result_ttl_seconds,
        nx=True,
    )
    if finalized:
        inflight_after = await redis_client.decr(inflight_key(activity_id))
        if inflight_after <= 0:
            await redis_client.delete(inflight_key(activity_id))
        if inflight_after < 0:
            await redis_client.set(inflight_key(activity_id), 0)
    await redis_client.set(
        result_key(activity_id, request_id),
        result_code,
        ex=result_ttl_seconds,
    )


async def consume_once(
    redis_client,
    session_maker: async_sessionmaker[AsyncSession] = SessionMaker,
    stream_key: str = SECKILL_STREAM_KEY,
    group_name: str = SECKILL_STREAM_GROUP,
    consumer_name: str = "default-consumer",
    max_retries: int = DEFAULT_MAX_RETRIES,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> bool:
    await ensure_consumer_group(
        redis_client,
        stream_key=stream_key,
        group_name=group_name,
    )
    records = await _safe_xreadgroup(
        redis_client,
        group_name=group_name,
        consumer_name=consumer_name,
        stream_key=stream_key,
    )
    stream_entries = _coerce_entries(records)
    if not stream_entries:
        claimed = await _safe_xautoclaim(
            redis_client,
            group_name=group_name,
            consumer_name=consumer_name,
            stream_key=stream_key,
            lease_seconds=lease_seconds,
        )
        stream_entries = _coerce_autoclaim_entries(claimed)
    if not stream_entries:
        return False

    event_id, payload = stream_entries[0]

    try:
        activity_id = int(_payload_value(payload, "activity_id"))
        user_id = int(_payload_value(payload, "user_id"))
        request_id = _payload_value(payload, "request_id")
    except Exception:
        await redis_client.xack(stream_key, group_name, event_id)
        await redis_client.xdel(stream_key, event_id)
        return True

    retry_count = 0
    async with session_maker() as lease_session:
        async with lease_session.begin():
            lease_status, retry_count = await acquire_processing_lease(
                session=lease_session,
                activity_id=activity_id,
                request_id=request_id,
                processor_id=consumer_name,
                lease_seconds=lease_seconds,
            )
            if lease_status == LeaseAcquireStatus.TERMINAL.value:
                _ = await reconcile_once(
                    redis_client=redis_client,
                    activity_id=activity_id,
                    request_id=request_id,
                    session_maker=session_maker,
                )
                await redis_client.xack(stream_key, group_name, event_id)
                await redis_client.xdel(stream_key, event_id)
                return True
            if lease_status == LeaseAcquireStatus.LEASED_BY_OTHER.value:
                return False

    try:
        async with session_maker() as session:
            async with session.begin():
                _ = await confirm_order_once(
                    session=session,
                    activity_id=activity_id,
                    user_id=user_id,
                    request_id=request_id,
                )
                await mark_success(
                    session=session,
                    activity_id=activity_id,
                    request_id=request_id,
                )
    except (SeckillActivityNotFoundError, SeckillDbStockExhaustedError) as exc:
        async with session_maker() as failed_session:
            async with failed_session.begin():
                await mark_failed_final(
                    session=failed_session,
                    activity_id=activity_id,
                    request_id=request_id,
                    last_error=str(exc),
                )
        _ = await reconcile_once(
            redis_client=redis_client,
            activity_id=activity_id,
            request_id=request_id,
            session_maker=session_maker,
        )
        await redis_client.xack(stream_key, group_name, event_id)
        await redis_client.xdel(stream_key, event_id)
        return True
    except Exception as exc:
        if retry_count >= max_retries:
            async with session_maker() as failed_session:
                async with failed_session.begin():
                    await mark_failed_final(
                        session=failed_session,
                        activity_id=activity_id,
                        request_id=request_id,
                        last_error=str(exc),
                    )
            _ = await reconcile_once(
                redis_client=redis_client,
                activity_id=activity_id,
                request_id=request_id,
                session_maker=session_maker,
            )
            await redis_client.xack(stream_key, group_name, event_id)
            await redis_client.xdel(stream_key, event_id)
            return True

        async with session_maker() as retry_session:
            async with retry_session.begin():
                await mark_retryable_failure(
                    session=retry_session,
                    activity_id=activity_id,
                    request_id=request_id,
                    last_error=str(exc),
                )
        # keep in pending list for re-claim by lease timeout
        return False

    await _finalize_request(
        redis_client,
        activity_id=activity_id,
        request_id=request_id,
        result_code="SUCCESS",
        result_ttl_seconds=SUCCESS_TTL_SECONDS,
    )
    await redis_client.xack(stream_key, group_name, event_id)
    await redis_client.xdel(stream_key, event_id)
    return True
