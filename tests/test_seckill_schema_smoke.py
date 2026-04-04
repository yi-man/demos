import subprocess
import sys

import sqlalchemy as sa

from orders.core.db.alembic_utils import build_mysql_sync_url


def test_seckill_tables_exist_after_upgrade():
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        capture_output=True,
        text=True,
    )

    engine = sa.create_engine(build_mysql_sync_url())
    inspector = sa.inspect(engine)

    assert inspector.has_table("seckill_activities")
    assert inspector.has_table("seckill_orders")
    assert inspector.has_table("seckill_stock_ledgers")
