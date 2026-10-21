"""Read-only diagnostics: row counts per table and policy state distribution.

Run inside the API container: ``python -m app.tools.dbcounts``. Prints counts only, no row data.
"""

import json

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_engine
from app.db_history import PolicyStateRow

TABLES = (
    "policy_states",
    "policy_definitions",
    "policy_initiatives",
    "policy_assignments",
    "policy_exemptions",
    "estate_resources",
    "estate_snapshots",
    "defender_snapshots",
    "metric_snapshots",
    "machine_status_snapshots",
)


def collect(session: Session) -> dict[str, object]:
    out: dict[str, object] = {}
    for table in TABLES:
        out[table] = session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
    states = session.execute(
        select(PolicyStateRow.compliance_state, func.count()).group_by(
            PolicyStateRow.compliance_state
        )
    ).all()
    out["policy_state_distribution"] = {str(k): int(v) for k, v in states}
    out["definitions_with_category"] = session.execute(
        text("SELECT count(*) FROM policy_definitions WHERE category IS NOT NULL")
    ).scalar_one()
    return out


def check_category_diagnostics(session: Session) -> dict[str, object]:
    """Counts only: stored source category values and how the current resolver classifies them."""
    from collections import Counter

    from app.db import CheckRow
    from app.domain.categories import configured_overrides, derive_category, resolve_category

    overrides = configured_overrides()
    rows = list(session.scalars(select(CheckRow)))
    resolved = [resolve_category(r.name, r.check_key, r.category, overrides) for r in rows]
    return {
        "checks": len(rows),
        "storedSourceCategory": dict(Counter(r.category or "(none)" for r in rows)),
        "resolvedCategory": dict(Counter(x.category for x in resolved)),
        "resolvedSource": dict(Counter(x.source for x in resolved)),
        "uncategorizedButDerivable": sum(
            1
            for r, x in zip(rows, resolved, strict=True)
            if x.category == "Uncategorized" and derive_category(r.name) is not None
        ),
        "overrides": len(overrides),
    }


def main() -> None:
    with Session(get_engine(get_settings().database_url)) as session:
        print(json.dumps(collect(session), indent=2, default=str))
        print(json.dumps(check_category_diagnostics(session), indent=2, default=str))


if __name__ == "__main__":
    main()
