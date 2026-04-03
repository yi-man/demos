from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import CHAR as MySQLChar
from sqlalchemy.dialects.mysql import TIMESTAMP as MySQLTimestamp
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    currency: Mapped[str] = mapped_column(MySQLChar(3), nullable=False, default="CNY")

    subtotal_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=0
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=0
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=0
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        MySQLTimestamp(fsp=6),
        server_default=text("CURRENT_TIMESTAMP(6)"),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        MySQLTimestamp(fsp=6),
        server_default=text("CURRENT_TIMESTAMP(6)"),
        onupdate=text("CURRENT_TIMESTAMP(6)"),
        nullable=False,
    )

    items: Mapped[list[OrderItem]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    order: Mapped[Order] = relationship("Order", back_populates="items")


class SeckillActivity(Base):
    __tablename__ = "seckill_activities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sku_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    start_at: Mapped[datetime.datetime] = mapped_column(
        MySQLTimestamp(fsp=6), nullable=False
    )
    end_at: Mapped[datetime.datetime] = mapped_column(
        MySQLTimestamp(fsp=6), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    total_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    db_sold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        MySQLTimestamp(fsp=6),
        server_default=text("CURRENT_TIMESTAMP(6)"),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        MySQLTimestamp(fsp=6),
        server_default=text("CURRENT_TIMESTAMP(6)"),
        onupdate=text("CURRENT_TIMESTAMP(6)"),
        nullable=False,
    )


class SeckillOrder(Base):
    __tablename__ = "seckill_orders"
    __table_args__ = (
        UniqueConstraint(
            "activity_id",
            "request_id",
            name="uq_seckill_orders_activity_id_request_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    activity_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("seckill_activities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    order_no: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    created_at: Mapped[datetime.datetime] = mapped_column(
        MySQLTimestamp(fsp=6),
        server_default=text("CURRENT_TIMESTAMP(6)"),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        MySQLTimestamp(fsp=6),
        server_default=text("CURRENT_TIMESTAMP(6)"),
        onupdate=text("CURRENT_TIMESTAMP(6)"),
        nullable=False,
    )


class SeckillStockLedger(Base):
    __tablename__ = "seckill_stock_ledgers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    activity_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("seckill_activities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    biz_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        MySQLTimestamp(fsp=6),
        server_default=text("CURRENT_TIMESTAMP(6)"),
        nullable=False,
    )
