from orders.core.cache.order_cache import build_order_cache_key


def test_build_order_cache_key():
    assert build_order_cache_key(123) == "orders:by_id:123"
