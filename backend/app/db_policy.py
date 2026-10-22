"""Estate-wide Azure Policy tables: metadata, exemptions, inventory, snapshots, Defender posture."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PolicyDefinitionRow(Base):
    """Policy definition metadata; ids are stored lower-cased."""

    __tablename__ = "policy_definitions"

    definition_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(String(24))
    effect: Mapped[str | None] = mapped_column(String(48))
    policy_type: Mapped[str | None] = mapped_column(String(24))
    mode: Mapped[str | None] = mapped_column(String(48))
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    domain: Mapped[str | None] = mapped_column(String(32))
    domain_source: Mapped[str | None] = mapped_column(String(16))
    domain_confidence: Mapped[str | None] = mapped_column(String(16))
    domain_version: Mapped[int | None] = mapped_column(Integer)


class PolicyInitiativeRow(Base):
    __tablename__ = "policy_initiatives"

    initiative_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    policy_type: Mapped[str | None] = mapped_column(String(24))
    definition_count: Mapped[int | None] = mapped_column(Integer)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PolicyAssignmentRow(Base):
    __tablename__ = "policy_assignments"
    __table_args__ = (Index("ix_policy_assignments_sub", "subscription_id"),)

    assignment_id: Mapped[str] = mapped_column(Text, primary_key=True)
    subscription_id: Mapped[str] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text)
    definition_id: Mapped[str | None] = mapped_column(Text)
    is_initiative: Mapped[bool] = mapped_column(Boolean, default=False)
    enforcement_mode: Mapped[str | None] = mapped_column(String(24))
    not_scopes_count: Mapped[int] = mapped_column(Integer, default=0)
    parameters: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("collection_runs.run_id"))


class PolicyExemptionRow(Base):
    __tablename__ = "policy_exemptions"
    __table_args__ = (Index("ix_policy_exemptions_sub", "subscription_id"),)

    exemption_id: Mapped[str] = mapped_column(Text, primary_key=True)
    subscription_id: Mapped[str] = mapped_column(String(36))
    scope: Mapped[str] = mapped_column(Text)
    assignment_id: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(24))
    expires_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("collection_runs.run_id"))


class CategoryOverrideRow(Base):
    """Reviewer-assigned domain; editing is gated like other shared configuration."""

    __tablename__ = "category_overrides"
    __table_args__ = (
        UniqueConstraint("target", "kind", "pattern", name="uq_category_overrides_match"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    target: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    pattern: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EstateResourceRow(Base):
    """Inventory with a configured whitelist of tag keys (never all tags)."""

    __tablename__ = "estate_resources"
    __table_args__ = (Index("ix_estate_resources_sub", "subscription_id"),)

    resource_id: Mapped[str] = mapped_column(Text, primary_key=True)
    subscription_id: Mapped[str] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(Text)
    resource_type: Mapped[str] = mapped_column(Text)
    resource_group: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("collection_runs.run_id"))


class EstateSnapshotRow(Base):
    """Per run and subscription aggregates, summed over authorized subscriptions for trends."""

    __tablename__ = "estate_snapshots"
    __table_args__ = (
        UniqueConstraint("run_id", "subscription_id", name="uq_estate_snapshots_run_sub"),
        Index("ix_estate_snapshots_at", "snapshot_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("collection_runs.run_id"))
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    subscription_id: Mapped[str] = mapped_column(String(36))
    collection_status: Mapped[str] = mapped_column(String(32))
    metrics: Mapped[dict[str, object]] = mapped_column(JSONB)


class DefenderSnapshotRow(Base):
    __tablename__ = "defender_snapshots"
    __table_args__ = (
        UniqueConstraint("run_id", "subscription_id", name="uq_defender_snapshots_run_sub"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("collection_runs.run_id"))
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    subscription_id: Mapped[str] = mapped_column(String(36))
    available: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text)
    secure_score: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    standards: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB)
