from __future__ import annotations


def stock_key(activity_id: int) -> str:
    return f"seckill:stock:{activity_id}"


def inflight_key(activity_id: int) -> str:
    return f"seckill:inflight:{activity_id}"


def req_key(activity_id: int, request_id: str) -> str:
    return f"seckill:req:{activity_id}:{request_id}"


def result_key(activity_id: int, request_id: str) -> str:
    return f"seckill:result:{activity_id}:{request_id}"


def finalized_key(activity_id: int, request_id: str) -> str:
    return f"seckill:finalized:{activity_id}:{request_id}"
