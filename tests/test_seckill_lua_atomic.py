from __future__ import annotations

import redis

from orders.core.settings import settings
from orders.seckill.keys import req_key, result_key, stock_key
from orders.seckill.service import run_pre_deduct


def test_lua_decrement_is_atomic_and_idempotent() -> None:
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    activity_id = 101
    first_request_id = "req-atomic-1"
    second_request_id = "req-atomic-2"
    ttl_seconds = 30

    keys_to_cleanup = [
        stock_key(activity_id),
        req_key(activity_id, first_request_id),
        result_key(activity_id, first_request_id),
        req_key(activity_id, second_request_id),
        result_key(activity_id, second_request_id),
    ]
    client.delete(*keys_to_cleanup)
    client.set(stock_key(activity_id), 1)

    first = run_pre_deduct(
        client, activity_id, first_request_id, ttl_seconds=ttl_seconds
    )
    duplicate = run_pre_deduct(
        client, activity_id, first_request_id, ttl_seconds=ttl_seconds
    )
    sold_out = run_pre_deduct(
        client, activity_id, second_request_id, ttl_seconds=ttl_seconds
    )

    assert first == "ACCEPTED"
    assert duplicate == "DUPLICATE"
    assert sold_out == "SOLD_OUT"
    assert int(client.get(stock_key(activity_id)) or 0) == 0
    assert client.get(result_key(activity_id, first_request_id)) == "PENDING"
    assert client.exists(req_key(activity_id, first_request_id)) == 1

    client.delete(*keys_to_cleanup)
