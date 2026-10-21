"""Export jobs and audit events (I09). Artifacts are short-lived; audit rows are retained."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ExportJobRow(Base):
    __tablename__ = "export_jobs"
    __table_args__ = (
        Index("ix_export_jobs_owner", "owner_oid"),
        Index("ix_export_jobs_exp", "expires_at"),
    )

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_oid: Mapped[str] = mapped_column(String(64))
    tenant_id: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(32))
    family: Mapped[str] = mapped_column(String(48))
    subscription_filter: Mapped[str | None] = mapped_column(String(36))
    # Subscriptions the owner was authorized for at creation; re-verified on every download.
    scope_subscription_ids: Mapped[str] = mapped_column(Text, default="")
    snapshot_id: Mapped[int | None] = mapped_column(BigInteger)
    snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    truncated: Mapped[bool] = mapped_column(default=False)
    content_type: Mapped[str | None] = mapped_column(String(64))
    filename: Mapped[str | None] = mapped_column(String(128))
    artifact: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExportAuditRow(Base):
    """Who did what with which job. Never holds artifact content, tokens or secrets."""

    __tablename__ = "export_audit"
    __table_args__ = (Index("ix_export_audit_at", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_oid: Mapped[str] = mapped_column(String(64))
    event: Mapped[str] = mapped_column(String(32))
    job_id: Mapped[str | None] = mapped_column(String(36))
    detail: Mapped[str] = mapped_column(Text, default="")
