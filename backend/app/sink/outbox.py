"""Durable outbox: idempotent enqueue, batched delivery with retry scheduling, status summary."""

import json
import random
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db_sink import STATUS_DEAD, STATUS_DELIVERED, STATUS_PENDING, LogsOutboxRow
from app.sink import schema
from app.sink.client import (
    LogsIngestionClient,
    PermanentSinkError,
    SinkError,
    TransientSinkError,
)

ENQUEUE_CHUNK = 500
INLINE_ATTEMPTS = 3
INLINE_BASE_DELAY = 1.0
INLINE_MAX_DELAY = 30.0


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def enqueue(
    session: Session,
    items: Iterable[tuple[str, dict[str, Any]]],
    run_id: int | None,
    now: datetime,
) -> int:
    """Store rows for delivery. Re-enqueueing an existing (stream, RecordKey) is a no-op."""
    added = 0
    chunk: list[tuple[str, dict[str, Any]]] = []

    def flush() -> int:
        if not chunk:
            return 0
        by_stream: dict[str, list[dict[str, Any]]] = {}
        for table, row in chunk:
            schema.validate_row(table, row)
            by_stream.setdefault(schema.tables()[table].stream, []).append(row)
        count = 0
        for stream, rows in by_stream.items():
            keys = [r["RecordKey"] for r in rows]
            known = set(
                session.scalars(
                    select(LogsOutboxRow.record_key).where(
                        LogsOutboxRow.stream == stream, LogsOutboxRow.record_key.in_(keys)
                    )
                )
            )
            for row in rows:
                if row["RecordKey"] in known:
                    continue
                known.add(row["RecordKey"])
                session.add(
                    LogsOutboxRow(
                        stream=stream,
                        record_key=row["RecordKey"],
                        run_id=run_id,
                        payload=row,
                        status=STATUS_PENDING,
                        attempts=0,
                        created_at=now,
                        next_attempt_at=now,
                    )
                )
                count += 1
        session.flush()
        chunk.clear()
        return count

    for item in items:
        chunk.append(item)
        if len(chunk) >= ENQUEUE_CHUNK:
            added += flush()
    return added + flush()


@dataclass
class DrainResult:
    delivered: int = 0
    rescheduled: int = 0
    dead: int = 0
    stopped: str | None = None  # why delivery paused (kind of the last transient failure)


def _batches(
    rows: Sequence[LogsOutboxRow], max_bytes: int, max_records: int
) -> list[list[LogsOutboxRow]]:
    out: list[list[LogsOutboxRow]] = []
    cur: list[LogsOutboxRow] = []
    size = 2
    for row in rows:
        n = len(json.dumps(row.payload, separators=(",", ":"))) + 1
        if cur and (size + n > max_bytes or len(cur) >= max_records):
            out.append(cur)
            cur, size = [], 2
        cur.append(row)
        size += n
    if cur:
        out.append(cur)
    return out


class OutboxDelivery:
    def __init__(
        self,
        factory: sessionmaker[Session],
        client: LogsIngestionClient,
        *,
        max_bytes: int,
        max_records: int,
        max_attempts: int,
        retry_max: timedelta,
        max_records_per_drain: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[], float] = random.random,
    ) -> None:
        self._factory = factory
        self._client = client
        self._max_bytes = max_bytes
        self._max_records = max_records
        self._max_attempts = max_attempts
        self._retry_max = retry_max
        self._budget = max_records_per_drain
        self._clock = clock
        self._sleep = sleep
        self._rand = rand

    def drain(self) -> DrainResult:
        result = DrainResult()
        remaining = self._budget
        for table in schema.tables().values():
            while remaining > 0 and result.stopped is None:
                with self._factory() as session:
                    rows = list(
                        session.scalars(
                            select(LogsOutboxRow)
                            .where(
                                LogsOutboxRow.stream == table.stream,
                                LogsOutboxRow.status == STATUS_PENDING,
                                LogsOutboxRow.next_attempt_at <= self._clock(),
                            )
                            .order_by(LogsOutboxRow.id)
                            .limit(min(remaining, self._max_records * 5))
                        )
                    )
                    if not rows:
                        break
                    remaining -= len(rows)
                    for batch in _batches(rows, self._max_bytes, self._max_records):
                        self._deliver(session, table.stream, batch, result)
                        session.commit()  # persist delivery state per batch to limit duplicates
                        if result.stopped is not None:
                            break
            if result.stopped is not None:
                break
        return result

    def _send_with_retry(self, stream: str, batch: list[LogsOutboxRow]) -> None:
        sent_at = schema_time(self._clock())
        payload = [{**r.payload, "SentAt": sent_at} for r in batch]
        for attempt in range(INLINE_ATTEMPTS):
            try:
                self._client.send(stream, payload)
                return
            except TransientSinkError as exc:
                if attempt == INLINE_ATTEMPTS - 1:
                    raise
                delay = exc.retry_after
                if delay is None:
                    delay = min(INLINE_MAX_DELAY, INLINE_BASE_DELAY * 2.0**attempt) * (
                        0.5 + self._rand() / 2
                    )
                self._sleep(min(delay, INLINE_MAX_DELAY))

    def _deliver(
        self, session: Session, stream: str, batch: list[LogsOutboxRow], result: DrainResult
    ) -> None:
        now = self._clock()
        try:
            self._send_with_retry(stream, batch)
        except PermanentSinkError as exc:
            if len(batch) > 1:  # isolate the rejected row(s); good rows must still be delivered
                mid = len(batch) // 2
                for half in (batch[:mid], batch[mid:]):
                    self._deliver(session, stream, half, result)
                    if result.stopped is not None:
                        return
                return
            self._mark(batch[0], now, STATUS_DEAD, exc)
            result.dead += 1
            return
        except TransientSinkError as exc:
            for row in batch:
                row.attempts += 1
                if row.attempts >= self._max_attempts:
                    self._mark(row, now, STATUS_DEAD, exc)
                    result.dead += 1
                else:
                    self._reschedule(row, now, exc)
                    result.rescheduled += 1
            result.stopped = exc.describe()
            return
        for row in batch:
            row.attempts += 1
            row.status = STATUS_DELIVERED
            row.last_attempt_at = now
            row.delivered_at = now
            row.last_error = None
        result.delivered += len(batch)

    def _reschedule(self, row: LogsOutboxRow, now: datetime, exc: SinkError) -> None:
        backoff = min(
            self._retry_max.total_seconds(), 60.0 * 2.0 ** min(row.attempts, 12)
        ) * (0.5 + self._rand() / 2)
        if exc.retry_after is not None:
            backoff = max(backoff, min(exc.retry_after, self._retry_max.total_seconds()))
        row.last_attempt_at = now
        row.next_attempt_at = now + timedelta(seconds=backoff)
        row.last_error = exc.describe()

    @staticmethod
    def _mark(row: LogsOutboxRow, now: datetime, status: str, exc: SinkError) -> None:
        if status == STATUS_DEAD and row.attempts == 0:
            row.attempts = 1
        row.status = status
        row.last_attempt_at = now
        row.last_error = exc.describe()


def schema_time(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def purge_outbox(
    session: Session, now: datetime, delivered_keep: timedelta, dead_keep: datetime
) -> int:
    deleted = 0
    for stmt in (
        delete(LogsOutboxRow).where(
            LogsOutboxRow.status == STATUS_DELIVERED,
            LogsOutboxRow.delivered_at < now - delivered_keep,
        ),
        delete(LogsOutboxRow).where(
            LogsOutboxRow.status == STATUS_DEAD, LogsOutboxRow.created_at < dead_keep
        ),
    ):
        deleted += int(cast(CursorResult[Any], session.execute(stmt)).rowcount)
    return deleted


def delivery_summary(session: Session, now: datetime) -> dict[str, Any]:
    """Counts and ages only; no payloads, no scope names, no remote error text."""
    rows = session.execute(
        select(LogsOutboxRow.status, func.count()).group_by(LogsOutboxRow.status)
    ).all()
    counts: dict[str, int] = {str(status): int(n) for status, n in rows}
    oldest = session.scalar(
        select(func.min(LogsOutboxRow.created_at)).where(LogsOutboxRow.status == STATUS_PENDING)
    )
    last_ok = session.scalar(select(func.max(LogsOutboxRow.delivered_at)))
    last_error = session.scalars(
        select(LogsOutboxRow.last_error)
        .where(LogsOutboxRow.last_error.is_not(None))
        .order_by(LogsOutboxRow.last_attempt_at.desc())
        .limit(1)
    ).first()
    pending = int(counts.get(STATUS_PENDING, 0))
    dead = int(counts.get(STATUS_DEAD, 0))
    if dead:
        state = "degraded"
    elif pending:
        state = "backlog"
    else:
        state = "ok"
    return {
        "pending": pending,
        "delivered": int(counts.get(STATUS_DELIVERED, 0)),
        "dead": dead,
        "state": state,
        "oldestPendingAgeSeconds": (
            int((_utc(now) - _utc(oldest)).total_seconds()) if oldest else None
        ),
        "lastDeliveredAt": _utc(last_ok).isoformat() if last_ok else None,
        "lastError": last_error,
    }
