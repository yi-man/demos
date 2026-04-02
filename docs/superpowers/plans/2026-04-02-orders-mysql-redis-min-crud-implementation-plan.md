# Orders: MySQL + Redis Min CRUD Implementation Plan

I'm using the writing-plans skill to create the implementation plan.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement minimal Orders CRUD with MySQL persistence (via SQLAlchemy) and Redis caching (cache-aside + invalidation), including Alembic migrations and real integration tests.

**Architecture:** FastAPI endpoints call a service layer that uses `AsyncSession` to MySQL and `redis.asyncio.Redis` for caching. Alembic uses a sync engine (pymysql) to manage schema versions; cache consistency is maintained by deleting the per-order cache key after writes to `orders.status` (and after delete).

**Tech Stack:** FastAPI, SQLAlchemy 2.x (async), Alembic, `aiomysql` + `pymysql`, `redis` (async client), pydantic-settings, pytest + FastAPI TestClient.

---

## Task 1: Add dependencies + extend configuration (MySQL + Redis)

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/orders/core/settings.py`
- Modify: `src/orders/main.py` (wire router composition if needed)
- Modify: `src/orders/api/routes.py` (register orders router)

### Step 1: Write failing test (import/config sanity)

Create `tests/test_orders_config_smoke.py` (this test will fail until Settings exposes MySQL/Redis configuration keys).

```python
from orders.core.settings import settings


def test_orders_core_settings_has_mysql_redis_config():
    assert settings.mysql_host
    assert settings.mysql_port
    assert settings.mysql_user
    assert settings.mysql_database
    assert settings.redis_url.startswith("redis://")
```

### Step 2: Run test to verify it fails

Run:

```bash
uv run -- pytest tests/test_orders_config_smoke.py -q
```

Expected: FAIL (settings missing `mysql_host` / `redis_url` until Settings is extended).

### Step 3: Write minimal implementation

1) Update `pyproject.toml` dependencies:

- Add the following to `[project].dependencies`:

```toml
  "SQLAlchemy>=2.0.0",
  "alembic>=1.13.0",
  "pymysql>=1.1.0",
  "aiomysql>=0.2.0",
  "redis>=5.0.0",
```

2) Update `src/orders/core/settings.py` to read env vars:

Replace the file content with:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    # Keep existing defaults for the app (used by /healthz debug).
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 9600

    # MySQL connection pieces (use exact env names provided by user).
    mysql_host: str = Field(default="127.0.0.1", validation_alias="MYSQL_HOST")
    mysql_port: int = Field(default=3306, validation_alias="MYSQL_PORT")
    mysql_user: str = Field(default="root", validation_alias="MYSQL_USER")
    mysql_pass: str = Field(default="", validation_alias="MYSQL_PASS")
    mysql_database: str = Field(default="superman", validation_alias="MYSQL_DATABASE")

    # Redis connection URL.
    redis_url: str = Field(default="redis://127.0.0.1:6379", validation_alias="REDIS_URL")

    model_config = SettingsConfigDict(env_prefix="ORDERS_", extra="ignore")


settings = Settings()
```

3) Ensure router composition registers orders router.

Because currently `src/orders/api/routes.py` only includes health, add an `orders` router include. Create `src/orders/api/orders.py` in Task 5 (later). For now, keep `routes.py` minimal to avoid import errors by conditionally importing, or leave it for Task 5. To avoid breaking, do not modify `routes.py` in this task yet.

So, in this task only modify settings.

### Step 4: Run test to verify it passes

Run:

```bash
uv run -- pytest tests/test_orders_config_smoke.py -q
```

Expected: PASS.

### Step 5: Commit

```bash
git add pyproject.toml src/orders/core/settings.py tests/test_orders_config_smoke.py
git commit -m "feat: add MySQL/Redis settings and deps for orders CRUD"
```

---

## Task 2: Add SQLAlchemy models + Alembic scaffolding + initial migration

**Files:**
- Create: `src/orders/core/db/base.py`
- Create: `src/orders/core/db/__init__.py`
- Create: `src/orders/core/db/models.py`
- Create: `src/orders/core/db/alembic_utils.py` (helper to build DB URL)
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/2026_04_02_0001_initial_orders_tables.py`

### Step 1: Write failing test (migration exists + upgrades)

Create `tests/test_orders_migration_smoke.py`:

```python
import subprocess


def test_alembic_upgrade_head_smoke():
    # Use system path; Alembic will be added as dependency in Task 1.
    subprocess.run(["alembic", "upgrade", "head"], check=True, capture_output=True, text=True)
```

### Step 2: Run test to verify it fails

Run:

```bash
uv run -- pytest tests/test_orders_migration_smoke.py -q
```

Expected: FAIL (alembic config missing / upgrade not possible).

### Step 3: Write minimal implementation

1) Create `src/orders/core/db/base.py`:

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

2) Create `src/orders/core/db/models.py`:

```python
from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")

    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(6),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(6),
        onupdate=func.current_timestamp(6),
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
```

Note: we used `func.current_timestamp(6)` for `created_at/updated_at`. Alembic migration will encode server defaults via SQLAlchemy.

3) Create `src/orders/core/db/alembic_utils.py`:

```python
from orders.core.settings import settings


def build_mysql_sync_url() -> str:
    # Alembic migrations will run sync using pymysql.
    return (
        f"mysql+pymysql://{settings.mysql_user}:{settings.mysql_pass}"
        f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}"
    )
```

4) Create `alembic.ini`:

```ini
[alembic]
script_location = alembic
sqlalchemy.url = driver://user:pass@localhost/dbname

[loggers]
keys = root,sqlalchemy,alembic
level = WARN
handlers = console
qualname = alembic

[handlers]
keys = console
level = NOTSET
class = StreamHandler
formatter = generic

[formatters]
keys = generic
level = NOTSET
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %Y-%m-%d %H:%M:%S
```

5) Create `alembic/env.py`:

```python
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from orders.core.db.base import Base
from orders.core.db.alembic_utils import build_mysql_sync_url
from orders.core.db import models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = build_mysql_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = build_mysql_sync_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

6) Create `alembic/script.py.mako` (standard template minimal):

```python
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade():
${upgrades if upgrades else "    pass"}


def downgrade():
${downgrades if downgrades else "    pass"}
```

7) Create initial migration `alembic/versions/2026_04_02_0001_initial_orders_tables.py`:

```python
from alembic import op
import sqlalchemy as sa

revision = "2026_04_02_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="created"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="CNY"),
        sa.Column("subtotal_amount", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0.00")),
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0.00")),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0.00")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
    )

    op.create_table(
        "order_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("order_id", "line_no", name="uq_order_items_order_id_line_no"),
        sa.Index("ix_order_items_order_id", "order_id"),
    )


def downgrade():
    op.drop_table("order_items")
    op.drop_table("orders")
```

### Step 4: Run test to verify it passes

Run:

```bash
uv run -- pytest tests/test_orders_migration_smoke.py -q
```

Expected: PASS (schema exists).

### Step 5: Commit

```bash
git add pyproject.toml alembic.ini alembic/env.py alembic/script.py.mako alembic/versions src/orders/core/db/base.py src/orders/core/db/models.py src/orders/core/db/alembic_utils.py tests/test_orders_migration_smoke.py
git commit -m "feat: add alembic migrations and orders models"
```

---

## Task 3: Implement DB session + Redis cache services

**Files:**
- Create: `src/orders/core/db/session.py`
- Create: `src/orders/core/cache/__init__.py`
- Create: `src/orders/core/cache/order_cache.py`
- Create: `src/orders/core/redis/__init__.py`
- Create: `src/orders/core/redis/client.py`

### Step 1: Write failing test (cache key helpers)

Create `tests/test_orders_cache_helpers.py`:

```python
from orders.core.cache.order_cache import build_order_cache_key


def test_build_order_cache_key():
    assert build_order_cache_key(123) == "orders:by_id:123"
```

### Step 2: Run test to verify it fails

Run:

```bash
uv run -- pytest tests/test_orders_cache_helpers.py -q
```

Expected: FAIL (cache module missing).

### Step 3: Write minimal implementation

1) Create `src/orders/core/redis/client.py`:

```python
from redis.asyncio import Redis

from orders.core.settings import settings


def create_redis_client() -> Redis:
    # decode_responses=False keeps raw bytes; we will store JSON strings for simplicity.
    return Redis.from_url(settings.redis_url)
```

2) Create `src/orders/core/cache/order_cache.py`:

```python
import json
from typing import Any


def build_order_cache_key(order_id: int) -> str:
    return f"orders:by_id:{order_id}"


async def cache_set_order(redis, order_id: int, payload: dict[str, Any], ttl_seconds: int = 60) -> None:
    key = build_order_cache_key(order_id)
    # Ensure Decimal/other non-JSON types are safely serialized.
    value = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    await redis.set(key, value, ex=ttl_seconds)


async def cache_get_order(redis, order_id: int) -> dict[str, Any] | None:
    key = build_order_cache_key(order_id)
    raw = await redis.get(key)
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


async def cache_invalidate_order(redis, order_id: int) -> None:
    key = build_order_cache_key(order_id)
    await redis.delete(key)
```

3) Create `src/orders/core/db/session.py`:

```python
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orders.core.settings import settings


def build_mysql_async_url() -> str:
    return (
        f"mysql+aiomysql://{settings.mysql_user}:{settings.mysql_pass}"
        f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}"
    )


async_engine = create_async_engine(build_mysql_async_url(), pool_pre_ping=True)

SessionMaker = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionMaker() as session:
        yield session
```

### Step 4: Run test to verify it passes

Run:

```bash
uv run -- pytest tests/test_orders_cache_helpers.py -q
```

Expected: PASS.

### Step 5: Commit

```bash
git add src/orders/core/redis/client.py src/orders/core/cache/order_cache.py src/orders/core/db/session.py tests/test_orders_cache_helpers.py
git commit -m "feat: add db session and redis order cache helpers"
```

---

## Task 4: Implement Orders service layer (create/get/patch/delete)

**Files:**
- Create: `src/orders/api/schemas.py`
- Create: `src/orders/api/orders.py`
- Modify: `src/orders/api/routes.py`

### Step 1: Write failing test (endpoint existence)

Create `tests/test_orders_endpoints_smoke.py`:

```python
from fastapi.testclient import TestClient

from orders.main import app


def test_orders_post_route_exists():
    client = TestClient(app)
    resp = client.post(
        "/orders",
        json={
            "customer_name": "alice",
            "currency": "CNY",
            "tax_amount": "0.00",
            "items": [{"product_name": "book", "quantity": 1, "unit_price": "10.00"}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["customer_name"] == "alice"
    assert data["status"] == "created"
    assert len(data["items"]) == 1
```

### Step 2: Run test to verify it fails

Run:

```bash
uv run -- pytest tests/test_orders_endpoints_smoke.py -q
```

Expected: FAIL (POST `/orders` returns 404/405 until endpoints are implemented).

### Step 3: Write minimal implementation

1) Create request/response schemas in `src/orders/api/schemas.py`:

```python
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, condecimal, conint


class OrderItemCreate(BaseModel):
    product_name: str = Field(min_length=1, max_length=255)
    quantity: conint(gt=0)
    unit_price: condecimal(ge=Decimal("0.00"), max_digits=12, decimal_places=2)


class OrderCreateRequest(BaseModel):
    customer_name: str = Field(min_length=1, max_length=255)
    currency: str = Field(default="CNY", min_length=3, max_length=3)
    tax_amount: condecimal(ge=Decimal("0.00"), max_digits=12, decimal_places=2) = Decimal("0.00")
    status: Literal["created"] | None = "created"
    items: list[OrderItemCreate] = Field(min_length=1)


class OrderItemResponse(BaseModel):
    line_no: int
    product_name: str
    quantity: int
    unit_price: condecimal(max_digits=12, decimal_places=2)
    line_total: condecimal(max_digits=12, decimal_places=2)


class OrderResponse(BaseModel):
    id: int
    customer_name: str
    status: str
    currency: str
    subtotal_amount: condecimal(max_digits=12, decimal_places=2)
    tax_amount: condecimal(max_digits=12, decimal_places=2)
    total_amount: condecimal(max_digits=12, decimal_places=2)
    created_at: str
    updated_at: str
    items: list[OrderItemResponse]


class OrderStatusUpdateRequest(BaseModel):
    status: Literal["created", "paid", "fulfilled", "cancelled"]
```

2) Create `src/orders/api/orders.py` with endpoints + service logic:

```python
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from orders.api.schemas import (
    OrderCreateRequest,
    OrderItemResponse,
    OrderResponse,
    OrderStatusUpdateRequest,
)
from orders.core.cache.order_cache import (
    cache_get_order,
    cache_invalidate_order,
    cache_set_order,
)
from orders.core.db.models import Order, OrderItem
from orders.core.db.session import get_async_session
from orders.core.redis.client import create_redis_client


router = APIRouter(prefix="")

redis_client: Redis | None = None


def get_redis() -> Redis:
    global redis_client
    if redis_client is None:
        redis_client = create_redis_client()
    return redis_client


def quantize_amount(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def order_to_payload(order: Order) -> dict[str, Any]:
    items = [
        OrderItemResponse(
            line_no=item.line_no,
            product_name=item.product_name,
            quantity=item.quantity,
            unit_price=item.unit_price,
            line_total=item.line_total,
        ).model_dump(mode="json")
        for item in sorted(order.items, key=lambda it: it.line_no)
    ]

    return OrderResponse(
        id=order.id,
        customer_name=order.customer_name,
        status=order.status,
        currency=order.currency,
        subtotal_amount=order.subtotal_amount,
        tax_amount=order.tax_amount,
        total_amount=order.total_amount,
        created_at=str(order.created_at),
        updated_at=str(order.updated_at),
        items=items,
    ).model_dump(mode="json")


@router.post("/orders", response_model=OrderResponse)
async def post_order(
    body: OrderCreateRequest,
    db: AsyncSession = Depends(get_async_session),
):
    redis = get_redis()
    items = []
    subtotal = Decimal("0.00")
    for idx, it in enumerate(body.items, start=1):
        unit_price = Decimal(str(it.unit_price))
        line_total = quantize_amount(unit_price * Decimal(it.quantity))
        subtotal += line_total
        items.append(
            OrderItem(
                line_no=idx,
                product_name=it.product_name,
                quantity=it.quantity,
                unit_price=unit_price,
                line_total=line_total,
            )
        )

    tax_amount = quantize_amount(Decimal(str(body.tax_amount)))
    total_amount = quantize_amount(subtotal + tax_amount)

    order = Order(
        customer_name=body.customer_name,
        status="created",
        currency=body.currency,
        subtotal_amount=quantize_amount(subtotal),
        tax_amount=tax_amount,
        total_amount=total_amount,
        items=items,
    )

    db.add(order)
    await db.commit()
    # Reload with eager-loaded items to avoid async lazy-loading pitfalls.
    result = await db.execute(
        select(Order).options(selectinload(Order.items)).where(Order.id == order.id)
    )
    order = result.scalar_one()

    payload = order_to_payload(order)
    await cache_set_order(redis, order.id, payload)
    return payload


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_async_session),
):
    redis = get_redis()
    cached = await cache_get_order(redis, order_id)
    if cached is not None:
        return cached

    q = select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    result = await db.execute(q)
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")

    payload = order_to_payload(order)
    await cache_set_order(redis, order_id, payload)
    return payload


@router.patch("/orders/{order_id}", response_model=OrderResponse)
async def patch_order_status(
    order_id: int,
    body: OrderStatusUpdateRequest,
    db: AsyncSession = Depends(get_async_session),
):
    redis = get_redis()

    q = select(Order).where(Order.id == order_id)
    result = await db.execute(q)
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")

    order.status = body.status
    await db.commit()

    # Invalidate after successful DB write.
    await cache_invalidate_order(redis, order_id)

    # Reload with eager-loaded items for response.
    result2 = await db.execute(
        select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
    )
    order = result2.scalar_one()

    payload = order_to_payload(order)
    return payload


@router.delete("/orders/{order_id}")
async def delete_order(
    order_id: int,
    db: AsyncSession = Depends(get_async_session),
):
    redis = get_redis()

    q = select(Order).where(Order.id == order_id)
    result = await db.execute(q)
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")

    await db.delete(order)
    await db.commit()

    await cache_invalidate_order(redis, order_id)
    return {"status": "deleted"}
```

3) Modify `src/orders/api/routes.py` to include the orders router:

```python
from fastapi import APIRouter

from orders.api.health import router as health_router
from orders.api.orders import router as orders_router

router = APIRouter()
router.include_router(health_router)
router.include_router(orders_router)
```

### Step 4: Run test to verify it passes

Run:

```bash
uv run -- pytest tests/test_orders_endpoints_smoke.py -q
```

Expected: PASS (POST `/orders` should no longer be 404/405 once implemented).

### Step 5: Commit

```bash
git add src/orders/api/schemas.py src/orders/api/orders.py src/orders/api/routes.py tests/test_orders_endpoints_smoke.py
git commit -m "feat: implement orders CRUD endpoints with mysql + redis cache"
```

---

## Task 5: Add full integration tests (real MySQL + real Redis)

**Files:**
- Create: `tests/test_orders_crud_integration.py`

### Step 1: Write failing test (end-to-end cache invalidation)

Create `tests/test_orders_crud_integration.py`:

```python
from decimal import Decimal

from fastapi.testclient import TestClient
import redis as redis_sync

from orders.main import app
from orders.core.settings import settings


client = TestClient(app)


def redis_client():
    return redis_sync.Redis.from_url(settings.redis_url)


def test_orders_crud_cache_invalidation():
    r = redis_client()

    # Create order
    resp = client.post(
        "/orders",
        json={
            "customer_name": "alice",
            "currency": "CNY",
            "tax_amount": "1.00",
            "items": [
                {"product_name": "book", "quantity": 2, "unit_price": "10.00"},
                {"product_name": "pen", "quantity": 3, "unit_price": "2.50"},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    order_id = data["id"]

    key = f"orders:by_id:{order_id}"
    assert r.exists(key) == 1

    # Update status -> must invalidate cache
    resp2 = client.patch(f"/orders/{order_id}", json={"status": "paid"})
    assert resp2.status_code == 200

    assert r.exists(key) == 0

    # Re-read -> should repopulate cache
    resp3 = client.get(f"/orders/{order_id}")
    assert resp3.status_code == 200
    assert resp3.json()["status"] == "paid"
    assert r.exists(key) == 1

    # Delete -> cache key removed and GET returns 404
    resp4 = client.delete(f"/orders/{order_id}")
    assert resp4.status_code == 200
    assert r.exists(key) == 0

    resp5 = client.get(f"/orders/{order_id}")
    assert resp5.status_code == 404
```

### Step 2: Run test to verify it fails

Run:

```bash
uv run -- pytest tests/test_orders_crud_integration.py -q
```

Expected: FAIL until we ensure Alembic upgrade has been run and endpoints work with real DB/Redis.

### Step 3: Write minimal implementation

Update test execution to ensure schema exists:

In this plan, we will add a `conftest.py` fixture to upgrade schema once per test session (real env).

Create `tests/conftest.py`:

```python
import subprocess
import pytest


@pytest.fixture(scope="session", autouse=True)
def _upgrade_schema():
    subprocess.run(["alembic", "upgrade", "head"], check=True, capture_output=True, text=True)
```

Then implement the integration test as written in Step 1.

Note: cache key assertion relies on cache being written during `GET /orders/{id}` or `POST /orders`.

### Step 4: Run tests to verify they pass

Run:

```bash
uv run -- pytest -q
```

Expected: PASS provided MySQL and Redis are reachable using env vars from spec.

### Step 5: Commit

```bash
git add tests/conftest.py tests/test_orders_crud_integration.py
git commit -m "test: add real integration tests for orders mysql+redis"
```

---

## Task 6: Quality gates (ruff/format/typecheck) + small fixes

**Files:** modified as needed by earlier tasks

### Step 1: Run lint

```bash
uv run -- ruff check .
```

Expected: PASS.

### Step 2: Run format

```bash
uv run -- ruff format .
```

Expected: PASS with no diffs after formatting.

### Step 3: Run mypy

```bash
uv run -- mypy src tests
```

Expected: PASS or addressed type errors.

### Step 4: Commit (only if needed)

```bash
git status --porcelain=v1
git add -u
git commit -m "chore: fix lint/type issues after orders implementation"
```

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-02-orders-mysql-redis-min-crud-implementation-plan.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?

