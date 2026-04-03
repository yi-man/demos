from __future__ import annotations

import redis
from fastapi.testclient import TestClient

from orders.core.settings import settings
from orders.main import app
from orders.seckill.keys import req_key, result_key, stock_key


def test_attempt_then_result_pending() -> None:
    activity_id = 201
    request_id = "req-100"
    user_id = 1
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    keys_to_cleanup = [
        stock_key(activity_id),
        req_key(activity_id, request_id),
        result_key(activity_id, request_id),
    ]
    client.delete(*keys_to_cleanup)
    client.set(stock_key(activity_id), 1)

    with TestClient(app) as test_client:
        attempt_resp = test_client.post(
            f"/seckill/{activity_id}/attempt",
            json={"user_id": user_id, "request_id": request_id},
        )
        assert attempt_resp.status_code == 200
        assert attempt_resp.json()["code"] in {"ACCEPTED", "SOLD_OUT", "DUPLICATE"}

        result_resp = test_client.get(f"/seckill/{activity_id}/result/{request_id}")
        assert result_resp.status_code == 200
        assert result_resp.json()["code"] == "PENDING"

    client.delete(*keys_to_cleanup)
