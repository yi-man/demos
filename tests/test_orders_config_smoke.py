from orders.core.settings import Settings


def test_orders_core_settings_has_mysql_redis_config(monkeypatch):
    monkeypatch.setenv("MYSQL_HOST", "mysql.example.test")
    monkeypatch.setenv("MYSQL_PORT", "3307")
    monkeypatch.setenv("MYSQL_USER", "appuser")
    monkeypatch.setenv("MYSQL_DATABASE", "orders_test")
    monkeypatch.setenv("REDIS_URL", "redis://redis.example.test:6380")

    # Instantiate after env vars are set so the validation_alias env mapping
    # is exercised.
    settings = Settings()

    assert settings.mysql_host == "mysql.example.test"
    assert settings.mysql_port == 3307
    assert settings.mysql_user == "appuser"
    assert settings.mysql_database == "orders_test"
    assert settings.redis_url == "redis://redis.example.test:6380"
