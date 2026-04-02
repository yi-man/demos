from redis.asyncio import Redis

from orders.core.settings import settings


def create_redis_client() -> Redis:
    return Redis.from_url(settings.redis_url)
