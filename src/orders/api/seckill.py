from __future__ import annotations

from collections.abc import AsyncGenerator

import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from orders.core.db.models import SeckillActivity
from orders.core.db.session import get_async_session
from orders.core.redis.client import create_redis_client
from orders.seckill.schemas import AttemptRequest, AttemptResponse, ResultResponse
from orders.seckill.service import attempt, query_result

router = APIRouter(prefix="/seckill", tags=["seckill"])


async def get_redis_client() -> AsyncGenerator[Redis]:
    redis = create_redis_client()
    try:
        yield redis
    finally:
        await redis.aclose()


@router.post("/{activity_id}/attempt", response_model=AttemptResponse)
async def seckill_attempt(
    activity_id: int,
    payload: AttemptRequest,
    session: AsyncSession = Depends(get_async_session),
    redis: Redis = Depends(get_redis_client),
) -> AttemptResponse:
    activity = await session.get(SeckillActivity, activity_id)
    if activity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="seckill activity not found",
        )

    now = datetime.datetime.now(datetime.UTC)
    if activity.status != "online":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="seckill activity is not online",
        )
    if now < activity.start_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="seckill activity has not started",
        )
    if now >= activity.end_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="seckill activity has ended",
        )

    code = await attempt(
        redis_client=redis,
        activity_id=activity_id,
        user_id=payload.user_id,
        request_id=payload.request_id,
    )
    return AttemptResponse(code=code)


@router.get("/{activity_id}/result/{request_id}", response_model=ResultResponse)
async def seckill_result(
    activity_id: int,
    request_id: str,
    redis: Redis = Depends(get_redis_client),
) -> ResultResponse:
    code = await query_result(
        redis_client=redis,
        activity_id=activity_id,
        request_id=request_id,
    )
    return ResultResponse(code=code)
