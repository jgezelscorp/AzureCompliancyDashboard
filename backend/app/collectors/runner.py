"""Collection run orchestration: overlap prevention, partial status, snapshots, retention."""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import exists, func, select, text
from sqlalchemy.orm import Session

from app.azure.client import ArmAccessDenied, ArmClient, ArmError, PagingError
from app.collectors import estate, sources
from app.collectors.normalize import (
    FamilyClassifier,
    NormalizationError,
    normalize_assignment,
    normalize_machine,
    normalize_policy_state,
    normalize_report,
    parse_ts,
)
from app.collectors.persist import (
    insert_reports,
    purge_history,
    replace_policy_states,
    retention_cutoff,
    touch_subscriptions,
    upsert_assignments,
    upsert_machines,
)
from app.config import Settings
from app.db import CheckRow, CollectionRunRow, ReportRow
from app.domain.domain_store import recompute_domains
from app.metrics.estate_store import write_estate_snapshots
from app.metrics.store import load_bundle, write_snapshots
from app.models import Assignment, Machine, PolicyState, Report
from app.sink.service import LogsSink

log = logging.getLogger(__name__)

ADVISORY_LOCK_KEY = 0x41434431  # "ACD1"
MAX_NEW_REPORTS_PER_ASSIGNMENT = 3
LATE_ARRIVAL_WINDOW = timedelta(hours=48)
MAX_RECORDED_ERRORS = 200


def utcnow() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass
class MachineEvidence:
    assignments: list[Assignment] = field(default_factory=list)
    reports: list[Report] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)


@dataclass
class RunResult:
    run_id: int
    status: str
    counts: dict[str, int]
    errors: list[dict[str, str]]


def _entry(source: str, scope: str, kind: str) -> dict[str, str]:
    return {"source": source, "scope": scope, "kind": kind, "status": ""}


def _err(source: str, scope: str, exc: Exception) -> dict[str, str]:
    kind = "AccessDenied" if isinstance(exc, ArmAccessDenied) else type(exc).__name__
    status = str(exc.status) if isinstance(exc, ArmError) else ""
    return {"source": source, "scope": scope, "kind": kind, "status": status}


class CollectionRunner:
    def __init__(
        self,
        settings: Settings,
        session_factory: Callable[[], Session],
        client: ArmClient,
        clock: Callable[[], datetime] = utcnow,
        sink: LogsSink | None = None,
    ) -> None:
        self._sink = sink
        self._settings = settings
        self._session_factory = session_factory
        self._client = client
        self._clock = clock

    # --- run lifecycle -------------------------------------------------------------------
    def _start(self) -> int | None:
        """Atomically claim the run slot; returns None when another run is active."""
        now = self._clock()
        timeout = timedelta(minutes=self._settings.collection_run_timeout_minutes)
        with self._session_factory() as session, session.begin():
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": ADVISORY_LOCK_KEY})
            for run in session.scalars(
                select(CollectionRunRow).where(CollectionRunRow.status == "running")
            ):
                if now - _utc(run.started_at) > timeout:
                    run.status = "abandoned"
                    run.finished_at = now
                    run.error = "run exceeded timeout and was abandoned"
                else:
                    return None
            run = CollectionRunRow(
                started_at=now,
                status="running",
                scope=",".join(self._settings.subscription_ids),
            )
            session.add(run)
            session.flush()
            return run.run_id

    def run_once(self) -> RunResult | None:
        run_id = self._start()
        if run_id is None:
            log.info("collection skipped: another run is active")
            return None
        errors: list[dict[str, str]] = []
        counts: dict[str, int] = {}
        status = "failed"
        fatal: str | None = None
        try:
            status = self._collect(run_id, errors, counts)
        except Exception as exc:  # run must always be closed with a status
            log.exception("collection run failed")
            fatal = f"{type(exc).__name__}: {str(exc)[:300]}"
        self._finish(run_id, status, errors, counts, fatal)
        if self._sink is not None:
            try:
                self._sink.publish(run_id)
            except Exception:  # never alters the committed collection
                log.exception("Logs sink failed for run %s", run_id)
        return RunResult(run_id, status, counts, errors)

    def _finish(
        self,
        run_id: int,
        status: str,
        errors: list[dict[str, str]],
        counts: dict[str, int],
        fatal: str | None,
    ) -> None:
        with self._session_factory() as session, session.begin():
            run = session.get(CollectionRunRow, run_id)
            if run is None:  # pragma: no cover
                return
            run.status = status
            run.finished_at = self._clock()
            run.error = fatal
            run.checkpoint = {
                "counts": counts,
                "errors": errors[:MAX_RECORDED_ERRORS],
                "errorCount": len(errors),
            }

    # --- collection ----------------------------------------------------------------------
    def _collect(self, run_id: int, errors: list[dict[str, str]], counts: dict[str, int]) -> str:
        subs = list(self._settings.subscription_ids)
        if not subs:
            errors.append(_entry("config", "", "NoSubscriptions"))
            return "failed"
        started = self._clock()
        uncertain: set[str] = set()

        machines: dict[str, Machine] = {}
        try:
            arg = sources.query_resource_graph(self._client, sources.MACHINE_QUERY, subs)
        except (ArmError, PagingError) as exc:
            errors.append(_err("arg-query", "all", exc))
            return "failed"
        skipped = 0
        for row in arg.rows:
            try:
                m = normalize_machine(row)
            except (NormalizationError, ValueError):
                skipped += 1
                continue
            machines[m.machine_id] = m
        if arg.truncated:
            uncertain.update(subs)
            errors.append(_entry("arg-query", "all", "Truncated"))
        if skipped:
            errors.append(_entry("arg-query", str(skipped), "MalformedRows"))
        counts["machines"] = len(machines)

        known_latest, known_ids = self._known_reports()
        eligible = [m for m in machines.values() if m.eligibility == "Eligible"]
        evidence = self._collect_machines(eligible, known_latest, known_ids)

        states: dict[str, list[PolicyState]] = {}
        extras: dict[str, dict[tuple[str, str, str], dict[str, Any]]] = {}
        summaries: dict[str, dict[str, Any]] = {}
        assignment_meta: dict[str, list[dict[str, Any]]] = {}
        exemption_meta: dict[str, list[dict[str, Any]]] = {}
        defender: dict[str, tuple[bool, str | None, dict[str, object] | None, Any]] = {}
        classifier = FamilyClassifier(self._settings.policy_family_map)
        for sub in subs:
            try:
                raw = sources.query_policy_states(self._client, sub)
            except (ArmError, PagingError) as exc:
                errors.append(_err("policyinsights-querystates", sub, exc))
                continue
            parsed: list[PolicyState] = []
            sub_extras: dict[tuple[str, str, str], dict[str, Any]] = {}
            for item in raw:
                try:
                    state = normalize_policy_state(item, classifier)
                except (NormalizationError, ValueError):
                    errors.append(
                        {
                            "source": "policyinsights-querystates",
                            "scope": sub,
                            "kind": "MalformedRow",
                            "status": "",
                        }
                    )
                    continue
                parsed.append(state)
                key = (
                    state.resource_id,
                    state.policy_assignment_id,
                    state.policy_definition_reference_id or "",
                )
                sub_extras[key] = estate.state_extras(item)
            states[sub] = parsed
            extras[sub] = sub_extras
            try:
                summaries[sub] = sources.summarize_policy(self._client, sub)
            except (ArmError, PagingError) as exc:
                errors.append(_err("policyinsights-summarize", sub, exc))
            try:
                assignment_meta[sub] = [
                    am
                    for raw_a in sources.list_policy_assignments(self._client, sub)
                    if (am := estate.normalize_assignment_meta(raw_a))
                ]
            except (ArmError, PagingError) as exc:
                errors.append(_err("policy-assignments", sub, exc))
            try:
                exemption_meta[sub] = [
                    em
                    for raw_e in sources.list_policy_exemptions(self._client, sub)
                    if (em := estate.normalize_exemption(raw_e))
                ]
            except (ArmError, PagingError) as exc:
                errors.append(_err("policy-exemptions", sub, exc))
            if self._settings.defender_enabled:
                defender[sub] = self._collect_defender(sub)

        inventory: list[dict[str, Any]] | None = None
        if self._settings.estate_inventory_enabled:
            try:
                inv = sources.query_resource_graph(self._client, sources.RESOURCE_QUERY, subs)
                inventory = [
                    im
                    for row in inv.rows[: sources.MAX_INVENTORY_ROWS]
                    if (im := estate.normalize_inventory(row, self._settings.estate_tag_keys))
                ]
                if inv.truncated or len(inv.rows) > sources.MAX_INVENTORY_ROWS:
                    errors.append(_entry("arg-query", "inventory", "Truncated"))
            except (ArmError, PagingError) as exc:
                errors.append(_err("arg-query", "inventory", exc))

        cutoff = retention_cutoff(started, self._settings.retention_months)
        changes: dict[str, dict[str, Any]] = {}
        with self._session_factory() as session, session.begin():
            upsert_machines(session, machines.values(), started)
            touch_subscriptions(session, uncertain, started)
            session.flush()
            assignments = [a for e in evidence for a in e.assignments]
            upsert_assignments(session, assignments, run_id)
            session.flush()
            reports = [r for e in evidence for r in e.reports if r.end_time >= cutoff]
            counts["reportsInserted"] = insert_reports(session, reports, run_id)
            for sub, items in states.items():
                changes[sub] = replace_policy_states(session, sub, items, run_id, extras[sub])
            for sub, rows in assignment_meta.items():
                estate.replace_assignments(session, sub, rows, run_id)
            for sub, rows in exemption_meta.items():
                estate.replace_exemptions(session, sub, rows, run_id)
            if inventory is not None:
                counts["inventory"] = estate.replace_inventory(session, subs, inventory, run_id)
            for sub, (ok, reason, score, standards) in defender.items():
                estate.store_defender(session, run_id, started, sub, ok, reason, score, standards)
            counts["assignments"] = len(assignments)
            counts["policyStates"] = sum(len(v) for v in states.values())
            counts["policyAssignments"] = sum(len(v) for v in assignment_meta.values())
            counts["policyExemptions"] = sum(len(v) for v in exemption_meta.values())
        for e in evidence:
            errors.extend(e.errors)

        wanted: dict[str, bool] = {}
        for sub_extras in extras.values():
            for ex in sub_extras.values():
                if ex.get("initiative_id"):
                    wanted[ex["initiative_id"]] = True
        for items in states.values():
            for s in items:
                wanted.setdefault(s.policy_definition_id.lower(), False)
        for rows in assignment_meta.values():
            for a in rows:
                if a["is_initiative"]:
                    wanted[a["definition_id"]] = True
        with self._session_factory() as session, session.begin():
            meta = estate.resolve_metadata(session, self._client, started, wanted)
            counts["domainsStamped"] = sum(
                v for k, v in recompute_domains(session, force=True).items() if k != "version"
            )
        counts.update({f"definitions_{k}": v for k, v in meta.items()})

        status = "succeeded" if not errors else "partial"
        with self._session_factory() as session, session.begin():
            bundle = load_bundle(session, started, machines_seen_since=started)
            write_snapshots(
                session,
                run_id,
                started,
                status,
                bundle,
                timedelta(hours=self._settings.freshness_hours),
            )
            write_estate_snapshots(session, run_id, started, status, set(states), changes)
            purged = purge_history(session, started, self._settings.retention_months)
        counts.update({f"purged_{k}": v for k, v in purged.items()})
        counts["policySummaries"] = len(summaries)
        return status

    def _collect_defender(self, sub: str) -> tuple[bool, str | None, dict[str, object] | None, Any]:
        """Optional Microsoft Defender for Cloud posture; unavailable/unlicensed is not an error."""
        try:
            score = estate.normalize_secure_score(sources.list_secure_scores(self._client, sub))
            standards = estate.normalize_standards(
                sources.list_regulatory_standards(self._client, sub)
            )
        except (ArmError, PagingError) as exc:
            kind = "AccessDenied" if isinstance(exc, ArmAccessDenied) else type(exc).__name__
            return False, kind, None, None
        if score is None and not standards:
            return False, "NoData", None, None
        return True, None, score, standards

    def _known_reports(self) -> tuple[dict[str, datetime], set[str]]:
        """Reports already stored with checks; reports without checks are fetched again."""
        has_checks = exists().where(CheckRow.report_id == ReportRow.report_id)
        with self._session_factory() as session:
            rows = session.execute(
                select(ReportRow.assignment_id, func.max(ReportRow.end_time))
                .where(has_checks)
                .group_by(ReportRow.assignment_id)
            ).all()
            ids = set(session.scalars(select(ReportRow.report_id).where(has_checks)))
        return {a: _utc(t) for a, t in rows}, ids

    def _collect_machines(
        self, machines: list[Machine], known_latest: dict[str, datetime], known_ids: set[str]
    ) -> list[MachineEvidence]:
        def one(m: Machine) -> MachineEvidence:
            return self._collect_machine(m, known_latest, known_ids)

        workers = self._settings.collection_concurrency
        if workers <= 1 or len(machines) <= 1:
            return [one(m) for m in machines]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(one, machines))

    def _collect_machine(
        self, machine: Machine, known_latest: dict[str, datetime], known_ids: set[str]
    ) -> MachineEvidence:
        out = MachineEvidence()
        try:
            raw_assignments = sources.list_assignments(self._client, machine.machine_id)
        except (ArmError, PagingError) as exc:
            out.errors.append(_err("guestconfig-assignments", machine.machine_id, exc))
            return out
        for raw in raw_assignments:
            try:
                assignment = normalize_assignment(raw, machine.machine_id)
            except (NormalizationError, ValueError):
                out.errors.append(
                    {
                        "source": "guestconfig-assignments",
                        "scope": machine.machine_id,
                        "kind": "MalformedAssignment",
                        "status": "",
                    }
                )
                continue
            out.assignments.append(assignment)
            if assignment.baseline_family == "Other":
                continue
            try:
                self._collect_reports(assignment, known_latest, known_ids, out)
            except (ArmError, PagingError) as exc:
                out.errors.append(_err("guestconfig-reports", assignment.assignment_id, exc))
        return out

    def _collect_reports(
        self,
        assignment: Assignment,
        known_latest: dict[str, datetime],
        known_ids: set[str],
        out: MachineEvidence,
    ) -> None:
        listed = sources.list_reports(self._client, assignment.assignment_id)
        dated: list[tuple[datetime, dict[str, Any]]] = []
        for item in listed:
            props = item.get("properties")
            end = props.get("endTime") if isinstance(props, dict) else None
            ts = parse_ts(end)
            if ts is not None and isinstance(item.get("id"), str):
                dated.append((ts, item))
        dated.sort(key=lambda t: t[0], reverse=True)
        newest_known = known_latest.get(assignment.assignment_id)
        wanted = [
            it
            for ts, it in dated
            if (newest_known is None or ts > newest_known - LATE_ARRIVAL_WINDOW)
            and str(it["id"]).lower() not in known_ids
        ][:MAX_NEW_REPORTS_PER_ASSIGNMENT]
        for item in wanted:
            try:
                detail = sources.get_report(self._client, str(item["id"]))
                out.reports.append(normalize_report(detail, assignment))
            except ArmError as exc:
                out.errors.append(_err("guestconfig-report-detail", assignment.assignment_id, exc))
            except (NormalizationError, ValueError):
                out.errors.append(
                    {
                        "source": "guestconfig-report-detail",
                        "scope": assignment.assignment_id,
                        "kind": "MalformedReport",
                        "status": "",
                    }
                )
