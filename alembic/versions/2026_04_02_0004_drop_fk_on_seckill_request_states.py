import sqlalchemy as sa

from alembic import op

revision = "2026_04_02_0004"
down_revision = "2026_04_02_0003"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    constraint_name = bind.execute(
        sa.text(
            """
            SELECT CONSTRAINT_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'seckill_request_states'
              AND COLUMN_NAME = 'activity_id'
              AND REFERENCED_TABLE_NAME = 'seckill_activities'
            LIMIT 1
            """
        )
    ).scalar_one_or_none()
    if constraint_name is not None:
        op.drop_constraint(
            constraint_name,
            "seckill_request_states",
            type_="foreignkey",
        )


def downgrade():
    op.create_foreign_key(
        "seckill_request_states_ibfk_1",
        "seckill_request_states",
        "seckill_activities",
        ["activity_id"],
        ["id"],
        ondelete="RESTRICT",
    )
