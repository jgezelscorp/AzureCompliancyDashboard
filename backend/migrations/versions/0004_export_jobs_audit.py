"""export jobs and audit events

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "export_jobs",
        sa.Column("job_id", sa.String(36), primary_key=True),
        sa.Column("owner_oid", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("family", sa.String(48), nullable=False),
        sa.Column("subscription_filter", sa.String(36)),
        sa.Column("scope_subscription_ids", sa.Text, nullable=False, server_default=""),
        sa.Column("snapshot_id", sa.BigInteger),
        sa.Column("snapshot_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("truncated", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("content_type", sa.String(64)),
        sa.Column("filename", sa.String(128)),
        sa.Column("artifact", sa.LargeBinary),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_export_jobs_owner", "export_jobs", ["owner_oid"])
    op.create_index("ix_export_jobs_exp", "export_jobs", ["expires_at"])
    op.create_table(
        "export_audit",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor_oid", sa.String(64), nullable=False),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("job_id", sa.String(36)),
        sa.Column("detail", sa.Text, nullable=False, server_default=""),
    )
    op.create_index("ix_export_audit_at", "export_audit", ["at"])


def downgrade() -> None:
    op.drop_table("export_audit")
    op.drop_table("export_jobs")
