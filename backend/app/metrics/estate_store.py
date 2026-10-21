"""Persist per-subscription estate aggregates so trends and deltas accumulate with every run."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_policy import EstateSnapshotRow
from app.metrics.policy import load_estate, snapshot_metrics


def write_estate_snapshots(
    session: Session,
    run_id: int,
    snapshot_at: datetime,
    status: str,
    subscriptions: set[str],
    changes: dict[str, dict[str, Any]],
) -> int:
    """One row per subscription whose policy states were collected in this run.

    A subscription whose collection failed gets no row, which shows up as a gap in the trend.
    """
    data = load_estate(session, frozenset(s.lower() for s in subscriptions))
    by_sub: dict[str, list[dict[str, Any]]] = {s.lower(): [] for s in subscriptions}
    for s in data.states:
        by_sub[s["sub"]].append(s)
    inventory: dict[str, int] = {s: 0 for s in by_sub}
    for rid in data.resources:
        parts = rid.split("/")
        if len(parts) > 2 and parts[2] in inventory:
            inventory[parts[2]] += 1
    written = 0
    for sub, states in by_sub.items():
        previous = session.scalars(
            select(EstateSnapshotRow.snapshot_at)
            .where(EstateSnapshotRow.subscription_id == sub)
            .order_by(EstateSnapshotRow.snapshot_at.desc())
            .limit(1)
        ).first()
        metrics = snapshot_metrics(
            states,
            [e for e in data.exemptions if e["sub"] == sub],
            inventory[sub],
            snapshot_at,
            changes.get(sub.lower()) or changes.get(sub),
        )
        metrics["previousSnapshotAt"] = previous.isoformat() if previous else None
        session.add(
            EstateSnapshotRow(
                run_id=run_id,
                snapshot_at=snapshot_at,
                subscription_id=sub,
                collection_status=status,
                metrics=metrics,
            )
        )
        written += 1
    return written
