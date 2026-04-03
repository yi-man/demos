import sqlalchemy as sa

from alembic import op

revision = "2026_04_02_0002"
down_revision = "2026_04_02_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "seckill_activities",
        sa.Column(
            "id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False
        ),
        sa.Column("sku_id", sa.BigInteger(), nullable=False),
        sa.Column("start_at", sa.dialects.mysql.TIMESTAMP(fsp=6), nullable=False),
        sa.Column("end_at", sa.dialects.mysql.TIMESTAMP(fsp=6), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="draft"
        ),
        sa.Column("total_stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("db_sold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.dialects.mysql.TIMESTAMP(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.dialects.mysql.TIMESTAMP(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            server_onupdate=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Index("ix_seckill_activities_sku_id", "sku_id"),
    )

    op.create_table(
        "seckill_orders",
        sa.Column(
            "id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False
        ),
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("order_no", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="created"
        ),
        sa.Column(
            "created_at",
            sa.dialects.mysql.TIMESTAMP(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.dialects.mysql.TIMESTAMP(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            server_onupdate=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"], ["seckill_activities.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "activity_id",
            "request_id",
            name="uq_seckill_orders_activity_id_request_id",
        ),
        sa.UniqueConstraint("order_no", name="uq_seckill_orders_order_no"),
        sa.Index("ix_seckill_orders_activity_id", "activity_id"),
        sa.Index("ix_seckill_orders_user_id", "user_id"),
    )

    op.create_table(
        "seckill_stock_ledgers",
        sa.Column(
            "id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False
        ),
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("biz_id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.dialects.mysql.TIMESTAMP(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"], ["seckill_activities.id"], ondelete="RESTRICT"
        ),
        sa.Index("ix_seckill_stock_ledgers_activity_id", "activity_id"),
        sa.Index("ix_seckill_stock_ledgers_biz_id", "biz_id"),
    )


def downgrade():
    op.drop_table("seckill_stock_ledgers")
    op.drop_table("seckill_orders")
    op.drop_table("seckill_activities")
