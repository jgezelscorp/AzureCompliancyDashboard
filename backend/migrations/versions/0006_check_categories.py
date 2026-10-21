"""derived check category columns (raw source evidence is untouched)

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("checks", sa.Column("derived_category", sa.Text))
    op.add_column("checks", sa.Column("category_source", sa.String(16)))
    op.add_column("checks", sa.Column("category_rule_version", sa.Integer))


def downgrade() -> None:
    op.drop_column("checks", "category_rule_version")
    op.drop_column("checks", "category_source")
    op.drop_column("checks", "derived_category")
