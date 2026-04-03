from __future__ import annotations


class SeckillActivityNotFoundError(Exception):
    """Raised when a seckill activity does not exist."""


class SeckillDbStockExhaustedError(Exception):
    """Raised when MySQL-side stock is already exhausted."""
