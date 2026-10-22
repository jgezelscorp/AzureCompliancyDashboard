"""Persistence helpers for security domains: overrides and stamped classification columns.

Stamping rewrites only app-derived columns; raw evidence (check status, reasons, the source
category, policy states) is never modified. Reads classify on the fly with the same pure
functions, so results are current even if stamped columns lag a version.
"""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import CheckRow
from app.db_policy import CategoryOverrideRow, PolicyDefinitionRow
from app.domain.categories import derive_category
from app.domain.domains import (
    DomainOverride,
    classify_check,
    classify_policy,
    configured_domain_overrides,
    taxonomy_version,
)


def load_overrides(session: Session) -> tuple[DomainOverride, ...]:
    """Reviewer overrides (database) first, then repo/env overrides."""
    rows = session.scalars(select(CategoryOverrideRow).order_by(CategoryOverrideRow.id)).all()
    db = tuple(
        DomainOverride(r.target, r.kind, r.pattern, r.domain)  # type: ignore[arg-type]
        for r in rows
    )
    return db + configured_domain_overrides()


def stamp_check(row: CheckRow, overrides: tuple[DomainOverride, ...]) -> None:
    r = classify_check(
        row.name,
        row.check_key,
        row.benchmark_control_id,
        row.category,
        row.derived_category or derive_category(row.name),
        overrides,
    )
    row.domain, row.domain_source = r.domain, r.source
    row.domain_confidence, row.domain_version = r.confidence, r.version


def stamp_definition(row: PolicyDefinitionRow, overrides: tuple[DomainOverride, ...]) -> None:
    r = classify_policy(row.category, row.display_name, row.definition_id, overrides)
    row.domain, row.domain_source = r.domain, r.source
    row.domain_confidence, row.domain_version = r.confidence, r.version


def recompute_domains(session: Session, force: bool = False) -> dict[str, int]:
    """Re-stamp rows whose stored taxonomy version is missing or older (all rows when forced)."""
    version = taxonomy_version()
    overrides = load_overrides(session)
    stale = or_(
        PolicyDefinitionRow.domain_version.is_(None), PolicyDefinitionRow.domain_version != version
    )
    q = select(PolicyDefinitionRow)
    definitions = session.scalars(q if force else q.where(stale)).all()
    for d in definitions:
        stamp_definition(d, overrides)
    cq = select(CheckRow)
    cstale = or_(CheckRow.domain_version.is_(None), CheckRow.domain_version != version)
    checks = session.scalars(cq if force else cq.where(cstale)).all()
    for c in checks:
        stamp_check(c, overrides)
    return {"definitions": len(definitions), "checks": len(checks), "version": version}
