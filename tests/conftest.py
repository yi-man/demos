from __future__ import annotations

import asyncio
import subprocess
import sys
from collections.abc import Generator

import pytest

from orders.core.db.session import async_engine


@pytest.fixture(scope="session", autouse=True)
def ensure_alembic_schema_upgraded() -> None:
    """Ensure database schema is up to date before any test runs."""
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(autouse=True)
def dispose_async_engine_after_test() -> Generator[None, None, None]:
    """Prevent pooled aiomysql connections from leaking across event loops."""
    yield
    asyncio.run(async_engine.dispose())
