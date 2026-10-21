"""Durable outbox for the optional Log Analytics sink (I08).

Rows are written after the PostgreSQL collection has committed. Delivery state lives only here,
so a sink outage never changes collection runs, evidence or snapshots.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
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

STATUS_PENDING = "pending"
STATUS_DELIVERED = "delivered"
STATUS_DEAD = "dead"


class LogsOutboxRow(Base):
    __tablename__ = "logs_outbox"
    __table_args__ = (
        UniqueConstraint("stream", "record_key", name="uq_logs_outbox_stream_key"),
        Index("ix_logs_outbox_due", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stream: Mapped[str] = mapped_column(String(96))
    record_key: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("collection_runs.run_id"))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
