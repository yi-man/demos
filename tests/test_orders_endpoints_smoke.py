from fastapi.testclient import TestClient

from orders.main import app


def test_orders_post_smoke() -> None:
    client = TestClient(app)
    response = client.post(
        "/orders",
        json={
            "customer_name": "smoke-user",
            "items": [{"product_name": "book", "quantity": 2, "unit_price": "9.99"}],
        },
    )
    assert response.status_code == 200

    data = response.json()
    expected_keys = {
        "id",
        "customer_name",
        "status",
        "currency",
        "subtotal_amount",
        "tax_amount",
        "total_amount",
        "created_at",
        "updated_at",
        "items",
    }
    assert expected_keys.issubset(data.keys())
    assert data["status"] == "created"
    assert data["currency"] == "CNY"
    assert len(data["items"]) == 1
    assert data["subtotal_amount"] == "19.98"
    assert data["tax_amount"] == "0.00"
    assert data["total_amount"] == "19.98"
    assert data["items"][0]["line_total"] == "19.98"
