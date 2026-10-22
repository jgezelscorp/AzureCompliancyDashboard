"""security-domain columns on checks and policy definitions, plus reviewer overrides

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _domain_columns(table: str) -> None:
    op.add_column(table, sa.Column("domain", sa.String(32)))
    op.add_column(table, sa.Column("domain_source", sa.String(16)))
    op.add_column(table, sa.Column("domain_confidence", sa.String(16)))
    op.add_column(table, sa.Column("domain_version", sa.Integer))


def upgrade() -> None:
    _domain_columns("checks")
    _domain_columns("policy_definitions")
    op.create_table(
        "category_overrides",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("target", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("pattern", sa.Text, nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("target", "kind", "pattern", name="uq_category_overrides_match"),
    )


def downgrade() -> None:
    op.drop_table("category_overrides")
    for table in ("policy_definitions", "checks"):
        for col in ("domain_version", "domain_confidence", "domain_source", "domain"):
            op.drop_column(table, col)
