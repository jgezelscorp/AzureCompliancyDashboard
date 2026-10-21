"""durable onboarded scopes

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "onboarded_scopes",
        sa.Column("subscription_id", sa.String(36), primary_key=True),
        sa.Column("registered_by", sa.Text, nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("onboarded_scopes")
