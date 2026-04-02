from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from orders.api.schemas import OrderCreateRequest, OrderPatchRequest, OrderResponse
from orders.core.cache.order_cache import (
    cache_get_order,
    cache_invalidate_order,
    cache_set_order,
)
from orders.core.db.models import Order, OrderItem
from orders.core.db.session import get_async_session
from orders.core.redis.client import create_redis_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/orders", tags=["orders"])

MONEY_QUANT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


async def get_redis_client() -> AsyncGenerator[Redis]:
    redis = create_redis_client()
    try:
        yield redis
    finally:
        await redis.aclose()


async def _fetch_order(
    session: AsyncSession,
    order_id: int,
) -> Order | None:
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.id == order_id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


@router.post("", response_model=OrderResponse)
async def create_order(
    payload: OrderCreateRequest,
    session: AsyncSession = Depends(get_async_session),
    redis: Redis = Depends(get_redis_client),
) -> OrderResponse:
    subtotal_amount = _money(
        sum(
            (_money(item.unit_price) * item.quantity for item in payload.items),
            Decimal("0.00"),
        )
    )
    tax_amount = _money(payload.tax_amount)
    total_amount = _money(subtotal_amount + tax_amount)

    order = Order(
        customer_name=payload.customer_name,
        status="created",
        currency=payload.currency,
        subtotal_amount=subtotal_amount,
        tax_amount=tax_amount,
        total_amount=total_amount,
    )

    for idx, item in enumerate(payload.items, start=1):
        unit_price = _money(item.unit_price)
        line_total = _money(unit_price * item.quantity)
        order.items.append(
            OrderItem(
                line_no=idx,
                product_name=item.product_name,
                quantity=item.quantity,
                unit_price=unit_price,
                line_total=line_total,
            )
        )

    session.add(order)
    await session.commit()

    created = await _fetch_order(session=session, order_id=order.id)
    if created is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    response_model = OrderResponse.model_validate(created)
    try:
        await cache_set_order(
            redis=redis,
            order_id=response_model.id,
            payload=response_model.model_dump(mode="json"),
        )
    except Exception:
        logger.exception("failed to set order cache for order_id=%s", response_model.id)

    return response_model


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    session: AsyncSession = Depends(get_async_session),
    redis: Redis = Depends(get_redis_client),
) -> OrderResponse:
    try:
        cached = await cache_get_order(redis=redis, order_id=order_id)
        if cached is not None:
            return OrderResponse.model_validate(cached)
    except Exception:
        logger.exception("failed to get order cache for order_id=%s", order_id)

    order = await _fetch_order(session=session, order_id=order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="order not found",
        )

    response_model = OrderResponse.model_validate(order)
    try:
        await cache_set_order(
            redis=redis,
            order_id=order_id,
            payload=response_model.model_dump(mode="json"),
        )
    except Exception:
        logger.exception("failed to set order cache for order_id=%s", order_id)

    return response_model


@router.patch("/{order_id}", response_model=OrderResponse)
async def patch_order_status(
    order_id: int,
    payload: OrderPatchRequest,
    session: AsyncSession = Depends(get_async_session),
    redis: Redis = Depends(get_redis_client),
) -> OrderResponse:
    order = await _fetch_order(session=session, order_id=order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="order not found",
        )

    order.status = payload.status
    await session.commit()

    updated = await _fetch_order(session=session, order_id=order_id)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="order not found",
        )

    try:
        await cache_invalidate_order(redis=redis, order_id=order_id)
    except Exception:
        logger.exception("failed to invalidate order cache for order_id=%s", order_id)

    return OrderResponse.model_validate(updated)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    order_id: int,
    session: AsyncSession = Depends(get_async_session),
    redis: Redis = Depends(get_redis_client),
) -> Response:
    order = await _fetch_order(session=session, order_id=order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="order not found",
        )

    await session.delete(order)
    await session.commit()

    try:
        await cache_invalidate_order(redis=redis, order_id=order_id)
    except Exception:
        logger.exception("failed to invalidate order cache for order_id=%s", order_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
