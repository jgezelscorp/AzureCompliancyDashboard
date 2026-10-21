"""durable outbox for the optional Log Analytics sink

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "logs_outbox",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("stream", sa.String(96), nullable=False),
        sa.Column("record_key", sa.String(64), nullable=False),
        sa.Column("run_id", sa.BigInteger, sa.ForeignKey("collection_runs.run_id")),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("next_attempt_at", TS, nullable=False),
        sa.Column("last_attempt_at", TS),
        sa.Column("delivered_at", TS),
        sa.Column("last_error", sa.Text),
        sa.UniqueConstraint("stream", "record_key", name="uq_logs_outbox_stream_key"),
    )
    op.create_index("ix_logs_outbox_due", "logs_outbox", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_logs_outbox_due", table_name="logs_outbox")
    op.drop_table("logs_outbox")
