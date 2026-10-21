"""collection history: policy states and metric snapshots

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "policy_states",
        sa.Column("resource_id", sa.Text, primary_key=True),
        sa.Column("policy_assignment_id", sa.Text, primary_key=True),
        sa.Column("reference_id", sa.Text, primary_key=True, server_default=""),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("policy_definition_id", sa.Text, nullable=False),
        sa.Column("baseline_family", sa.String(48), nullable=False),
        sa.Column("compliance_state", sa.String(16), nullable=False),
        sa.Column("is_compliant", sa.Boolean),
        sa.Column("state_timestamp", TS, nullable=False),
        sa.Column("run_id", sa.BigInteger, sa.ForeignKey("collection_runs.run_id")),
    )
    op.create_index("ix_policy_states_subscription", "policy_states", ["subscription_id"])

    op.create_table(
        "metric_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id", sa.BigInteger, sa.ForeignKey("collection_runs.run_id"), nullable=False
        ),
        sa.Column("snapshot_at", TS, nullable=False),
        sa.Column("family", sa.String(48), nullable=False),
        sa.Column("collection_status", sa.String(32), nullable=False),
        sa.Column("policy_compliance", postgresql.JSONB, nullable=False),
        sa.Column("check_pass_rate", postgresql.JSONB, nullable=False),
        sa.Column("coverage", postgresql.JSONB, nullable=False),
        sa.Column("unclassified_policy_states", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("run_id", "family", name="uq_metric_snapshots_run_family"),
    )
    op.create_index("ix_metric_snapshots_at", "metric_snapshots", ["snapshot_at"])

    op.create_table(
        "machine_status_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "snapshot_id",
            sa.BigInteger,
            sa.ForeignKey("metric_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("machine_id", sa.Text, nullable=False),
        sa.Column("family", sa.String(48), nullable=False),
        sa.Column("evidence_quality", sa.String(32), nullable=False),
        sa.Column("reported_state", sa.String(16)),
        sa.Column("green", sa.Boolean, nullable=False),
    )
    op.create_index("ix_machine_status_snapshot", "machine_status_snapshots", ["snapshot_id"])


def downgrade() -> None:
    for table in ("machine_status_snapshots", "metric_snapshots", "policy_states"):
        op.drop_table(table)
