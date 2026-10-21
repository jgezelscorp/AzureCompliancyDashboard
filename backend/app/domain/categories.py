"""Versioned, rule-based check categorizer (pure functions, no I/O except override loading).

The rules live in ``check_categories.json`` and are shared with the workbook generator so the
app and the workbook cannot drift. The result is an app-derived heuristic grouping, not a
benchmark mapping.
"""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

CategorySource = Literal["source", "derived", "override", "unmapped"]

RULES_PATH = Path(__file__).with_name("check_categories.json")
UNCATEGORIZED = "Uncategorized"


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class Override:
    kind: Literal["exact", "prefix", "regex"]
    pattern: str
    category: str


@dataclass(frozen=True)
class Resolved:
    category: str
    source: CategorySource
    rule_version: int


@lru_cache
def load_rules() -> tuple[int, str, tuple[Rule, ...]]:
    data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    rules = tuple(
        Rule(r["id"], r["category"], re.compile(r["pattern"], re.IGNORECASE)) for r in data["rules"]
    )
    return int(data["rulesVersion"]), str(data["defaultCategory"]), rules


def rules_version() -> int:
    return load_rules()[0]


def derive_category(name: str) -> str | None:
    """First matching rule wins; None when no rule matches."""
    for rule in load_rules()[2]:
        if rule.pattern.search(name):
            return rule.category
    return None


def parse_overrides(raw: str) -> tuple[Override, ...]:
    """Parse a JSON list of {type: exact|prefix|regex, pattern, category}; invalid input raises."""
    if not raw.strip():
        return ()
    items = json.loads(raw)
    if not isinstance(items, list):
        raise ValueError("category overrides must be a JSON list")
    out: list[Override] = []
    for item in items:
        kind = item.get("type", "exact")
        pattern, category = item.get("pattern"), item.get("category")
        if kind not in ("exact", "prefix", "regex") or not pattern or not category:
            raise ValueError("each override needs type (exact|prefix|regex), pattern and category")
        if kind == "regex":
            re.compile(pattern)
        out.append(Override(kind, str(pattern), str(category)))
    return tuple(out)


def _override_matches(o: Override, name: str, key: str) -> bool:
    if o.kind == "exact":
        return o.pattern.lower() in (name.lower(), key.lower())
    if o.kind == "prefix":
        return name.lower().startswith(o.pattern.lower()) or key.lower().startswith(
            o.pattern.lower()
        )
    return bool(re.search(o.pattern, name, re.IGNORECASE) or re.search(o.pattern, key, re.I))


def resolve_category(
    name: str,
    check_key: str = "",
    source_category: str | None = None,
    overrides: tuple[Override, ...] = (),
) -> Resolved:
    """Precedence: override > source-provided > derived > Uncategorized (unmapped)."""
    version, default, _ = load_rules()
    for o in overrides:
        if _override_matches(o, name, check_key):
            return Resolved(o.category, "override", version)
    if source_category:
        return Resolved(source_category, "source", version)
    derived = derive_category(name)
    if derived:
        return Resolved(derived, "derived", version)
    return Resolved(default, "unmapped", version)


@lru_cache
def _overrides_for(inline: str, file_path: str) -> tuple[Override, ...]:
    merged = list(parse_overrides(inline))
    if file_path:
        merged = list(parse_overrides(Path(file_path).read_text(encoding="utf-8"))) + merged
    return tuple(merged)


def configured_overrides() -> tuple[Override, ...]:
    from app.config import get_settings

    s = get_settings()
    return _overrides_for(s.category_overrides, s.category_overrides_file)
