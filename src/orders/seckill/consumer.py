from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orders.core.db.session import SessionMaker
from orders.seckill.keys import result_key
from orders.seckill.repo import confirm_order_once

SECKILL_STREAM_KEY = "seckill:stream"
SUCCESS_TTL_SECONDS = 300


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
) -> bool:
    # Consume the newest pending event to avoid replaying stale stream history.
    stream_entries = await redis_client.xrevrange(stream_key, count=1)
    if not stream_entries:
        return False

    event_id, payload = stream_entries[0]

    activity_id = int(_payload_value(payload, "activity_id"))
    user_id = int(_payload_value(payload, "user_id"))
    request_id = _payload_value(payload, "request_id")

    async with session_maker() as session:
        async with session.begin():
            _ = await confirm_order_once(
                session=session,
                activity_id=activity_id,
                user_id=user_id,
                request_id=request_id,
            )

    await redis_client.set(
        result_key(activity_id, request_id),
        "SUCCESS",
        ex=SUCCESS_TTL_SECONDS,
    )
    await redis_client.xdel(stream_key, event_id)
    return True
