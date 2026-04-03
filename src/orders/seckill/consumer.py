from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orders.core.db.session import SessionMaker
from orders.seckill.compensation import reconcile_once
from orders.seckill.keys import result_key
from orders.seckill.repo import (
    confirm_order_once,
    mark_failed_final,
    mark_success,
    upsert_processing_state,
)

SECKILL_STREAM_KEY = "seckill:stream"
SUCCESS_TTL_SECONDS = 300
DEFAULT_MAX_RETRIES = 3


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


async def consume_once(
    redis_client,
    session_maker: async_sessionmaker[AsyncSession] = SessionMaker,
    stream_key: str = SECKILL_STREAM_KEY,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> bool:
    # Consume the newest pending event to avoid replaying stale stream history.
    stream_entries = await redis_client.xrevrange(stream_key, count=1)
    if not stream_entries:
        return False

    event_id, payload = stream_entries[0]

    try:
        activity_id = int(_payload_value(payload, "activity_id"))
        user_id = int(_payload_value(payload, "user_id"))
        request_id = _payload_value(payload, "request_id")
    except Exception:
        await redis_client.xdel(stream_key, event_id)
        return True

    async with session_maker() as state_session:
        async with state_session.begin():
            retry_count = await upsert_processing_state(
                session=state_session,
                activity_id=activity_id,
                request_id=request_id,
            )

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
    except ValueError as exc:
        if "seckill activity not found" not in str(exc):
            raise
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
            await redis_client.xdel(stream_key, event_id)
            return True
        return False

    await redis_client.set(
        result_key(activity_id, request_id),
        "SUCCESS",
        ex=SUCCESS_TTL_SECONDS,
    )
    await redis_client.xdel(stream_key, event_id)
    return True
