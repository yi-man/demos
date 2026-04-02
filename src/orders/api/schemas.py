from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OrderStatus = Literal["created", "paid", "fulfilled", "cancelled"]


class OrderItemCreate(BaseModel):
    product_name: str = Field(min_length=1, max_length=255)
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(
        ge=Decimal("0.00"),
        max_digits=12,
        decimal_places=2,
    )


class OrderCreateRequest(BaseModel):
    customer_name: str = Field(min_length=1, max_length=255)
    currency: str = Field(default="CNY", min_length=3, max_length=3)
    tax_amount: Decimal = Field(
        default=Decimal("0.00"),
        ge=Decimal("0.00"),
        max_digits=12,
        decimal_places=2,
    )
    items: list[OrderItemCreate] = Field(min_length=1)


class OrderPatchRequest(BaseModel):
    status: OrderStatus


class OrderItemResponse(BaseModel):
    line_no: int
    product_name: str
    quantity: int
    unit_price: Decimal = Field(max_digits=12, decimal_places=2)
    line_total: Decimal = Field(max_digits=12, decimal_places=2)

    model_config = ConfigDict(from_attributes=True)


class OrderResponse(BaseModel):
    id: int
    customer_name: str
    status: OrderStatus
    currency: str
    subtotal_amount: Decimal = Field(max_digits=12, decimal_places=2)
    tax_amount: Decimal = Field(max_digits=12, decimal_places=2)
    total_amount: Decimal = Field(max_digits=12, decimal_places=2)
    created_at: dt.datetime
    updated_at: dt.datetime
    items: list[OrderItemResponse]

    model_config = ConfigDict(from_attributes=True)
