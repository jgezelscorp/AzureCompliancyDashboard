"""Tables added for collection (I05): latest policy states and metric history snapshots."""

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


class PolicyStateRow(Base):
    """Latest Azure Policy state per resource x assignment x reference (not history)."""

    __tablename__ = "policy_states"
    __table_args__ = (Index("ix_policy_states_subscription", "subscription_id"),)

    resource_id: Mapped[str] = mapped_column(Text, primary_key=True)
    policy_assignment_id: Mapped[str] = mapped_column(Text, primary_key=True)
    reference_id: Mapped[str] = mapped_column(Text, primary_key=True, default="")
    subscription_id: Mapped[str] = mapped_column(String(36))
    policy_definition_id: Mapped[str] = mapped_column(Text)
    baseline_family: Mapped[str] = mapped_column(String(48))
    compliance_state: Mapped[str] = mapped_column(String(16))
    is_compliant: Mapped[bool | None] = mapped_column(Boolean)
    state_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("collection_runs.run_id"))


class MetricSnapshotRow(Base):
    """One row per collection run and baseline family; the three metrics stay separate."""

    __tablename__ = "metric_snapshots"
    __table_args__ = (
        UniqueConstraint("run_id", "family", name="uq_metric_snapshots_run_family"),
        Index("ix_metric_snapshots_at", "snapshot_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("collection_runs.run_id"))
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    family: Mapped[str] = mapped_column(String(48))
    collection_status: Mapped[str] = mapped_column(String(32))
    policy_compliance: Mapped[dict[str, object]] = mapped_column(JSONB)
    check_pass_rate: Mapped[dict[str, object]] = mapped_column(JSONB)
    coverage: Mapped[dict[str, object]] = mapped_column(JSONB)
    unclassified_policy_states: Mapped[int] = mapped_column(Integer, default=0)


class MachineStatusSnapshotRow(Base):
    __tablename__ = "machine_status_snapshots"
    __table_args__ = (Index("ix_machine_status_snapshot", "snapshot_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("metric_snapshots.id", ondelete="CASCADE"))
    machine_id: Mapped[str] = mapped_column(Text)
    family: Mapped[str] = mapped_column(String(48))
    evidence_quality: Mapped[str] = mapped_column(String(32))
    reported_state: Mapped[str | None] = mapped_column(String(16))
    green: Mapped[bool] = mapped_column(Boolean)
