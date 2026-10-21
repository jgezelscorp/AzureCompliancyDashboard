"""estate-wide Azure Policy: state attributes, metadata, exemptions, inventory, snapshots

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def run_fk() -> sa.ForeignKey:
    return sa.ForeignKey("collection_runs.run_id")


def upgrade() -> None:
    for name, kind in (
        ("resource_type", sa.Text),
        ("resource_group", sa.Text),
        ("location", sa.Text),
        ("assignment_name", sa.Text),
        ("definition_name", sa.Text),
        ("initiative_id", sa.Text),
        ("initiative_name", sa.Text),
        ("state_category", sa.Text),
        ("effect", sa.String(48)),
        ("group_names", JSONB),
    ):
        op.add_column("policy_states", sa.Column(name, kind))
    op.create_index("ix_policy_states_type", "policy_states", ["resource_type"])

    op.create_table(
        "policy_definitions",
        sa.Column("definition_id", sa.Text, primary_key=True),
        sa.Column("display_name", sa.Text),
        sa.Column("category", sa.Text),
        sa.Column("severity", sa.String(24)),
        sa.Column("effect", sa.String(48)),
        sa.Column("policy_type", sa.String(24)),
        sa.Column("mode", sa.String(48)),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("refreshed_at", TS, nullable=False),
    )
    op.create_table(
        "policy_initiatives",
        sa.Column("initiative_id", sa.Text, primary_key=True),
        sa.Column("display_name", sa.Text),
        sa.Column("category", sa.Text),
        sa.Column("policy_type", sa.String(24)),
        sa.Column("definition_count", sa.Integer),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("refreshed_at", TS, nullable=False),
    )
    op.create_table(
        "policy_assignments",
        sa.Column("assignment_id", sa.Text, primary_key=True),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text),
        sa.Column("scope", sa.Text),
        sa.Column("definition_id", sa.Text),
        sa.Column("is_initiative", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("enforcement_mode", sa.String(24)),
        sa.Column("not_scopes_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("parameters", JSONB),
        sa.Column("run_id", sa.BigInteger, run_fk()),
    )
    op.create_index("ix_policy_assignments_sub", "policy_assignments", ["subscription_id"])
    op.create_table(
        "policy_exemptions",
        sa.Column("exemption_id", sa.Text, primary_key=True),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("assignment_id", sa.Text),
        sa.Column("display_name", sa.Text),
        sa.Column("category", sa.String(24)),
        sa.Column("expires_on", TS),
        sa.Column("run_id", sa.BigInteger, run_fk()),
    )
    op.create_index("ix_policy_exemptions_sub", "policy_exemptions", ["subscription_id"])
    op.create_table(
        "estate_resources",
        sa.Column("resource_id", sa.Text, primary_key=True),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("resource_type", sa.Text, nullable=False),
        sa.Column("resource_group", sa.Text),
        sa.Column("location", sa.Text),
        sa.Column("tags", JSONB),
        sa.Column("run_id", sa.BigInteger, run_fk()),
    )
    op.create_index("ix_estate_resources_sub", "estate_resources", ["subscription_id"])
    op.create_table(
        "estate_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.BigInteger, run_fk(), nullable=False),
        sa.Column("snapshot_at", TS, nullable=False),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("collection_status", sa.String(32), nullable=False),
        sa.Column("metrics", JSONB, nullable=False),
        sa.UniqueConstraint("run_id", "subscription_id", name="uq_estate_snapshots_run_sub"),
    )
    op.create_index("ix_estate_snapshots_at", "estate_snapshots", ["snapshot_at"])
    op.create_table(
        "defender_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.BigInteger, run_fk(), nullable=False),
        sa.Column("snapshot_at", TS, nullable=False),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("available", sa.Boolean, nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("secure_score", JSONB),
        sa.Column("standards", JSONB),
        sa.UniqueConstraint("run_id", "subscription_id", name="uq_defender_snapshots_run_sub"),
    )


def downgrade() -> None:
    for table in (
        "defender_snapshots",
        "estate_snapshots",
        "estate_resources",
        "policy_exemptions",
        "policy_assignments",
        "policy_initiatives",
        "policy_definitions",
    ):
        op.drop_table(table)
    op.drop_index("ix_policy_states_type", "policy_states")
    for name in (
        "group_names",
        "effect",
        "state_category",
        "initiative_name",
        "initiative_id",
        "definition_name",
        "assignment_name",
        "location",
        "resource_group",
        "resource_type",
    ):
        op.drop_column("policy_states", name)
