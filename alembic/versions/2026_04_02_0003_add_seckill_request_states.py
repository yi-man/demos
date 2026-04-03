import sqlalchemy as sa

from alembic import op

revision = "2026_04_02_0003"
down_revision = "2026_04_02_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "seckill_request_states",
        sa.Column(
            "id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False
        ),
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="RECEIVED"
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=255), nullable=True),
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
        sa.UniqueConstraint(
            "activity_id",
            "request_id",
            name="uq_seckill_request_states_activity_id_request_id",
        ),
        sa.Index("ix_seckill_request_states_activity_id", "activity_id"),
    )


def downgrade():
    op.drop_table("seckill_request_states")
