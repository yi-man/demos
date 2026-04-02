from __future__ import annotations

import redis
from fastapi.testclient import TestClient

from orders.core.cache.order_cache import build_order_cache_key
from orders.core.settings import settings
from orders.main import app


def test_orders_crud_cache_integration_flow() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/orders",
            json={
                "customer_name": "integration-crud-user",
                "items": [
                    {"product_name": "keyboard", "quantity": 1, "unit_price": "199.00"}
                ],
            },
        )
        assert create_response.status_code == 200
        created = create_response.json()
        order_id = created["id"]
        cache_key = build_order_cache_key(order_id)

        redis_client = redis.Redis.from_url(settings.redis_url)
        try:
            assert redis_client.exists(cache_key) == 1

            patch_response = client.patch(
                f"/orders/{order_id}",
                json={"status": "paid"},
            )
            assert patch_response.status_code == 200
            patched = patch_response.json()
            assert patched["id"] == order_id
            assert patched["status"] == "paid"

            assert redis_client.exists(cache_key) == 0

            get_response = client.get(f"/orders/{order_id}")
            assert get_response.status_code == 200
            got = get_response.json()
            assert got["id"] == order_id
            assert got["status"] == "paid"
            assert redis_client.exists(cache_key) == 1

            delete_response = client.delete(f"/orders/{order_id}")
            assert delete_response.status_code == 204
            assert delete_response.text == ""
            assert redis_client.exists(cache_key) == 0

            get_after_delete = client.get(f"/orders/{order_id}")
            assert get_after_delete.status_code == 404
            assert get_after_delete.json()["detail"] == "order not found"
        finally:
            redis_client.close()
