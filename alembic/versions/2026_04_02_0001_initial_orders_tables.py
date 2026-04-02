import sqlalchemy as sa

from alembic import op

revision = "2026_04_02_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "orders",
        sa.Column(
            "id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False
        ),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="created"
        ),
        sa.Column(
            "currency",
            sa.dialects.mysql.CHAR(length=3),
            nullable=False,
            server_default="CNY",
        ),
        sa.Column(
            "subtotal_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "tax_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "total_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0.00"),
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
    )

    op.create_table(
        "order_items",
        sa.Column(
            "id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False
        ),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "order_id", "line_no", name="uq_order_items_order_id_line_no"
        ),
        sa.Index("ix_order_items_order_id", "order_id"),
    )


def downgrade():
    op.drop_table("order_items")
    op.drop_table("orders")
