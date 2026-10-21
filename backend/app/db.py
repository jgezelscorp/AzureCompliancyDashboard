"""SQLAlchemy table definitions for core entities (PostgreSQL)."""

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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MachineRow(Base):
    __tablename__ = "machines"

    machine_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))
    subscription_id: Mapped[str] = mapped_column(String(36), index=True)
    resource_group: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    os_type: Mapped[str] = mapped_column(String(16))
    os_name: Mapped[str | None] = mapped_column(Text)
    os_build: Mapped[str | None] = mapped_column(Text)
    eligibility: Mapped[str] = mapped_column(String(16))
    tags: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CollectionRunRow(Base):
    __tablename__ = "collection_runs"

    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32))
    scope: Mapped[str | None] = mapped_column(Text)
    checkpoint: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class AssignmentRow(Base):
    __tablename__ = "assignments"
    __table_args__ = (Index("ix_assignments_machine_id", "machine_id"),)

    assignment_id: Mapped[str] = mapped_column(Text, primary_key=True)
    machine_id: Mapped[str] = mapped_column(ForeignKey("machines.machine_id", ondelete="CASCADE"))
    baseline_family: Mapped[str] = mapped_column(String(48))
    guest_configuration_name: Mapped[str] = mapped_column(Text)
    guest_configuration_version: Mapped[str | None] = mapped_column(Text)
    policy_definition_id: Mapped[str | None] = mapped_column(Text)
    policy_definition_version: Mapped[str | None] = mapped_column(Text)
    policy_assignment_id: Mapped[str | None] = mapped_column(Text)
    assignment_hash: Mapped[str | None] = mapped_column(Text)
    parameter_hash: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(Text)
    include_arc_machines: Mapped[bool | None] = mapped_column(Boolean)
    compliance_status: Mapped[str] = mapped_column(String(16))
    last_compliance_status_checked: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    run_id: Mapped[int | None] = mapped_column(ForeignKey("collection_runs.run_id"))


class ReportRow(Base):
    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_reports_machine_end", "machine_id", "end_time"),
        Index("ix_reports_end_time", "end_time"),
    )

    report_id: Mapped[str] = mapped_column(Text, primary_key=True)
    assignment_id: Mapped[str] = mapped_column(
        ForeignKey("assignments.assignment_id", ondelete="CASCADE")
    )
    machine_id: Mapped[str] = mapped_column(ForeignKey("machines.machine_id", ondelete="CASCADE"))
    baseline_family: Mapped[str] = mapped_column(String(48))
    compliance_status: Mapped[str] = mapped_column(String(16))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    operation_type: Mapped[str | None] = mapped_column(Text)
    configuration_version: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("collection_runs.run_id"))


class CheckRow(Base):
    __tablename__ = "checks"
    __table_args__ = (UniqueConstraint("report_id", "check_key", name="uq_checks_report_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("reports.report_id", ondelete="CASCADE"), index=True
    )
    check_key: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    compliance_status: Mapped[str] = mapped_column(String(16))
    category: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(String(16))
    benchmark_control_id: Mapped[str | None] = mapped_column(Text)
    reasons: Mapped[list[dict[str, str | None]]] = mapped_column(JSONB)


class SettingRow(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, object]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by: Mapped[str | None] = mapped_column(Text)
