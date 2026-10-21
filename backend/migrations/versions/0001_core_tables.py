"""core tables

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "machines",
        sa.Column("machine_id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("resource_group", sa.Text, nullable=False),
        sa.Column("location", sa.Text),
        sa.Column("os_type", sa.String(16), nullable=False),
        sa.Column("os_name", sa.Text),
        sa.Column("os_build", sa.Text),
        sa.Column("eligibility", sa.String(16), nullable=False),
        sa.Column("tags", postgresql.JSONB),
        sa.Column("first_seen_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_machines_subscription_id", "machines", ["subscription_id"])

    op.create_table(
        "collection_runs",
        sa.Column("run_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("started_at", TS, nullable=False),
        sa.Column("finished_at", TS),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("scope", sa.Text),
        sa.Column("checkpoint", postgresql.JSONB),
        sa.Column("error", sa.Text),
    )

    op.create_table(
        "assignments",
        sa.Column("assignment_id", sa.Text, primary_key=True),
        sa.Column(
            "machine_id",
            sa.Text,
            sa.ForeignKey("machines.machine_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("baseline_family", sa.String(48), nullable=False),
        sa.Column("guest_configuration_name", sa.Text, nullable=False),
        sa.Column("guest_configuration_version", sa.Text),
        sa.Column("policy_definition_id", sa.Text),
        sa.Column("policy_definition_version", sa.Text),
        sa.Column("policy_assignment_id", sa.Text),
        sa.Column("assignment_hash", sa.Text),
        sa.Column("parameter_hash", sa.Text),
        sa.Column("content_hash", sa.Text),
        sa.Column("include_arc_machines", sa.Boolean),
        sa.Column("compliance_status", sa.String(16), nullable=False),
        sa.Column("last_compliance_status_checked", TS),
        sa.Column("run_id", sa.BigInteger, sa.ForeignKey("collection_runs.run_id")),
    )
    op.create_index("ix_assignments_machine_id", "assignments", ["machine_id"])

    op.create_table(
        "reports",
        sa.Column("report_id", sa.Text, primary_key=True),
        sa.Column(
            "assignment_id",
            sa.Text,
            sa.ForeignKey("assignments.assignment_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "machine_id",
            sa.Text,
            sa.ForeignKey("machines.machine_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("baseline_family", sa.String(48), nullable=False),
        sa.Column("compliance_status", sa.String(16), nullable=False),
        sa.Column("start_time", TS, nullable=False),
        sa.Column("end_time", TS, nullable=False),
        sa.Column("operation_type", sa.Text),
        sa.Column("configuration_version", sa.Text),
        sa.Column("run_id", sa.BigInteger, sa.ForeignKey("collection_runs.run_id")),
    )
    op.create_index("ix_reports_machine_end", "reports", ["machine_id", "end_time"])
    op.create_index("ix_reports_end_time", "reports", ["end_time"])

    op.create_table(
        "checks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "report_id",
            sa.Text,
            sa.ForeignKey("reports.report_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("check_key", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("compliance_status", sa.String(16), nullable=False),
        sa.Column("category", sa.Text),
        sa.Column("severity", sa.String(16)),
        sa.Column("benchmark_control_id", sa.Text),
        sa.Column("reasons", postgresql.JSONB, nullable=False),
        sa.UniqueConstraint("report_id", "check_key", name="uq_checks_report_key"),
    )
    op.create_index("ix_checks_report_id", "checks", ["report_id"])

    op.create_table(
        "settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", postgresql.JSONB, nullable=False),
        sa.Column("version", sa.Integer, server_default="1", nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.Text),
    )


def downgrade() -> None:
    for table in ("settings", "checks", "reports", "assignments", "collection_runs", "machines"):
        op.drop_table(table)
