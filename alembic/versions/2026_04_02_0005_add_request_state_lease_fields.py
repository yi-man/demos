import sqlalchemy as sa

from alembic import op

revision = "2026_04_02_0005"
down_revision = "2026_04_02_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "seckill_request_states",
        sa.Column("processor_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "seckill_request_states",
        sa.Column("lease_until", sa.dialects.mysql.TIMESTAMP(fsp=6), nullable=True),
    )


def downgrade():
    op.drop_column("seckill_request_states", "lease_until")
    op.drop_column("seckill_request_states", "processor_id")
