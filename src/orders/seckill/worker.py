from __future__ import annotations

import argparse
import asyncio
import signal
from typing import Final

from redis.asyncio import Redis as AsyncRedis

from orders.core.redis.client import create_redis_client
from orders.seckill.consumer import consume_once

DEFAULT_SLEEP_WHEN_EMPTY_S: Final[float] = 0.2


async def run_consumer_loop(
    redis_client: AsyncRedis,
    *,
    max_rounds: int | None = None,
    sleep_when_empty_s: float = DEFAULT_SLEEP_WHEN_EMPTY_S,
) -> int:
    """
    Consume seckill events from Redis Stream and confirm them into MySQL.

    This is intentionally a "minimal worker" wrapper around `consume_once`.
    On empty streams it sleeps briefly to avoid busy looping.
    """
    rounds = 0
    iterations = 0
    while max_rounds is None or iterations < max_rounds:
        iterations += 1
        try:
            ok = await consume_once(redis_client=redis_client)
        except Exception:
            await asyncio.sleep(sleep_when_empty_s)
            continue
        if ok:
            rounds += 1
            continue
        await asyncio.sleep(sleep_when_empty_s)
    return rounds


async def _run_forever(
    *,
    sleep_when_empty_s: float,
) -> None:
    redis_client = create_redis_client()
    stop_event = asyncio.Event()

    def _request_stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            # Some platforms (or signal handling in tests) may not support handlers.
            pass

    try:
        while not stop_event.is_set():
            await run_consumer_loop(
                redis_client,
                max_rounds=1,
                sleep_when_empty_s=sleep_when_empty_s,
            )
    finally:
        await redis_client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Orders seckill consumer worker")
    parser.add_argument(
        "--sleep-when-empty-s",
        type=float,
        default=DEFAULT_SLEEP_WHEN_EMPTY_S,
        help="Sleep duration when there is no event to consume.",
    )
    args = parser.parse_args()

    asyncio.run(_run_forever(sleep_when_empty_s=args.sleep_when_empty_s))


if __name__ == "__main__":
    main()
