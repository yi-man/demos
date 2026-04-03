from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import NoScriptError

from orders.seckill.consumer import SECKILL_STREAM_KEY
from orders.seckill.keys import req_key, result_key, stock_key

PreDeductCode = Literal["ACCEPTED", "DUPLICATE", "SOLD_OUT"]
ResultCode = Literal["PENDING", "SUCCESS", "FAILED", "NOT_FOUND"]

_DECREMENT_LUA_PATH = Path(__file__).with_name("lua") / "decrement.lua"


@lru_cache(maxsize=1)
def _decrement_script() -> str:
    return _DECREMENT_LUA_PATH.read_text(encoding="utf-8")


def run_pre_deduct(
    redis_client: Redis,
    activity_id: int,
    request_id: str,
    ttl_seconds: int = 300,
) -> PreDeductCode:
    script = _decrement_script()
    keys = [
        stock_key(activity_id),
        req_key(activity_id, request_id),
        result_key(activity_id, request_id),
    ]
    args = [str(ttl_seconds)]

    sha = redis_client.script_load(script)
    try:
        result = redis_client.evalsha(sha, len(keys), *keys, *args)
    except NoScriptError:
        result = redis_client.eval(script, len(keys), *keys, *args)

    if isinstance(result, bytes):
        return result.decode("utf-8")
    return result


async def attempt(
    redis_client: AsyncRedis,
    activity_id: int,
    user_id: int,
    request_id: str,
    ttl_seconds: int = 300,
) -> PreDeductCode:
    _ = user_id
    script = _decrement_script()
    keys = [
        stock_key(activity_id),
        req_key(activity_id, request_id),
        result_key(activity_id, request_id),
    ]
    args = [str(ttl_seconds)]

    sha = await redis_client.script_load(script)
    try:
        result = await redis_client.evalsha(sha, len(keys), *keys, *args)
    except NoScriptError:
        result = await redis_client.eval(script, len(keys), *keys, *args)

    code: PreDeductCode
    if isinstance(result, bytes):
        code = result.decode("utf-8")
    else:
        code = result

    if code == "ACCEPTED":
        await redis_client.xadd(
            SECKILL_STREAM_KEY,
            {
                "activity_id": str(activity_id),
                "user_id": str(user_id),
                "request_id": request_id,
            },
        )
    return code


async def query_result(
    redis_client: AsyncRedis,
    activity_id: int,
    request_id: str,
) -> ResultCode:
    result = await redis_client.get(result_key(activity_id, request_id))
    if result is None:
        return "NOT_FOUND"
    if isinstance(result, bytes):
        return result.decode("utf-8")
    return result
