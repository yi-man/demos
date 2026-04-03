from alembic import op

revision = "2026_04_02_0004"
down_revision = "2026_04_02_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        "seckill_request_states_ibfk_1",
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
