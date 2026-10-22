"""Security-domain classification (layer 2/3 of the categorization strategy).

Pure functions over ``domain_taxonomy.json``. A policy or check gets exactly one domain, so
domain counts never double count. Provenance (``source``) says where the answer came from and
``confidence`` says how much to trust it:

- ``override``: a reviewer or repo-managed override decided (always wins);
- ``source``: the Azure Policy definition's own metadata category (or a report-provided check
  category) mapped through the curated table;
- ``derived-high`` / ``derived-low``: app rules (check rules v1, benchmark section numbers or
  keyword rules); low means a heuristic on free text;
- ``unmapped``: nothing matched, the item sits in ``Other`` and in the review queue.

The result is an indicative reporting aid, not a benchmark or certification mapping.
"""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

TAXONOMY_PATH = Path(__file__).with_name("domain_taxonomy.json")

DomainSource = Literal["source", "derived", "override", "unmapped"]
Confidence = Literal["override", "source", "derived-high", "derived-low", "unmapped"]
CONFIDENCES: tuple[Confidence, ...] = (
    "override",
    "source",
    "derived-high",
    "derived-low",
    "unmapped",
)
SECTION_RE = re.compile(r"^\(?(\d+(?:\.\d+)*)")


@dataclass(frozen=True)
class DomainResult:
    domain: str
    source: DomainSource
    confidence: Confidence
    version: int
    rule: str | None = None


@dataclass(frozen=True)
class DomainOverride:
    target: Literal["policy", "check"]
    kind: Literal["exact", "prefix", "regex"]
    pattern: str
    domain: str


@dataclass(frozen=True)
class Taxonomy:
    version: int
    default: str
    labels: dict[str, str]
    policy_categories: dict[str, str]
    policy_keywords: tuple[tuple[str, str, re.Pattern[str]], ...]
    check_categories: dict[str, tuple[str, str]]
    check_sections: tuple[tuple[str, str, str], ...]
    frameworks: dict[str, Any]
    crosswalk: dict[str, dict[str, list[str]]]
    disclaimer: str
    raw: dict[str, Any]


@lru_cache
def load_taxonomy() -> Taxonomy:
    data = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    return Taxonomy(
        version=int(data["taxonomyVersion"]),
        default=data["defaultDomain"],
        labels={d["id"]: d["label"] for d in data["domains"]},
        policy_categories=data["policyCategoryMap"],
        policy_keywords=tuple(
            (r["id"], r["domain"], re.compile(r["pattern"], re.IGNORECASE))
            for r in data["policyKeywordRules"]
        ),
        check_categories={
            k: (v["domain"], v["confidence"]) for k, v in data["checkCategoryMap"].items()
        },
        check_sections=tuple(
            (r["id"], r["prefix"], r["domain"]) for r in data["checkSectionRules"]
        ),
        frameworks=data["frameworks"],
        crosswalk=data["crosswalk"],
        disclaimer=data["disclaimer"],
        raw=data,
    )


def taxonomy_version() -> int:
    return load_taxonomy().version


def domain_label(domain: str) -> str:
    return load_taxonomy().labels.get(domain, domain)


def valid_domain(domain: str) -> bool:
    return domain in load_taxonomy().labels


def parse_domain_overrides(raw: str) -> tuple[DomainOverride, ...]:
    """JSON list of {target: policy|check, type: exact|prefix|regex, pattern, domain}."""
    if not raw.strip():
        return ()
    items = json.loads(raw)
    if not isinstance(items, list):
        raise ValueError("domain overrides must be a JSON list")
    out: list[DomainOverride] = []
    for item in items:
        target, kind = item.get("target", "policy"), item.get("type", "exact")
        pattern, domain = item.get("pattern"), item.get("domain")
        if (
            target not in ("policy", "check")
            or kind not in ("exact", "prefix", "regex")
            or not pattern
            or not valid_domain(str(domain))
        ):
            raise ValueError("each domain override needs target, type, pattern and a known domain")
        if kind == "regex":
            re.compile(pattern)
        out.append(DomainOverride(target, kind, str(pattern), str(domain)))
    return tuple(out)


def _override_hit(o: DomainOverride, texts: tuple[str, ...]) -> bool:
    for t in texts:
        if not t:
            continue
        if o.kind == "exact" and t.lower() == o.pattern.lower():
            return True
        if o.kind == "prefix" and t.lower().startswith(o.pattern.lower()):
            return True
        if o.kind == "regex" and re.search(o.pattern, t, re.IGNORECASE):
            return True
    return False


def _override(
    overrides: tuple[DomainOverride, ...], target: str, texts: tuple[str, ...]
) -> DomainResult | None:
    for o in overrides:
        if o.target == target and _override_hit(o, texts):
            return DomainResult(o.domain, "override", "override", taxonomy_version())
    return None


def section_of(*candidates: str | None) -> str | None:
    for c in candidates:
        if c:
            m = SECTION_RE.match(c.strip())
            if m:
                return m.group(1)
    return None


def classify_policy(
    category: str | None,
    display_name: str | None,
    definition_id: str = "",
    overrides: tuple[DomainOverride, ...] = (),
) -> DomainResult:
    """Precedence: override > source category map > display-name keywords > unmapped."""
    t = load_taxonomy()
    hit = _override(overrides, "policy", (definition_id, display_name or ""))
    if hit:
        return hit
    if category:
        domain = t.policy_categories.get(category.strip().lower())
        if domain:
            return DomainResult(domain, "source", "source", t.version, f"cat:{category.lower()}")
    for rule_id, domain, pattern in t.policy_keywords:
        if display_name and pattern.search(display_name):
            return DomainResult(domain, "derived", "derived-low", t.version, rule_id)
    return DomainResult(t.default, "unmapped", "unmapped", t.version)


def classify_check(
    name: str,
    check_key: str = "",
    benchmark_control_id: str | None = None,
    source_category: str | None = None,
    derived_category: str | None = None,
    overrides: tuple[DomainOverride, ...] = (),
) -> DomainResult:
    """Precedence: override > source category > section number > rules-v1 category > keywords."""
    t = load_taxonomy()
    hit = _override(overrides, "check", (check_key, name))
    if hit:
        return hit
    if source_category:
        domain = t.policy_categories.get(source_category.strip().lower())
        if domain:
            return DomainResult(domain, "source", "source", t.version, f"cat:{source_category}")
    section = section_of(benchmark_control_id, name, check_key)
    if section:
        for rule_id, prefix, domain in t.check_sections:
            if section == prefix or section.startswith(prefix + "."):
                return DomainResult(domain, "derived", "derived-high", t.version, rule_id)
    if derived_category and derived_category in t.check_categories:
        domain, confidence = t.check_categories[derived_category]
        return DomainResult(
            domain,
            "derived",
            "derived-low" if confidence == "derived-low" else "derived-high",
            t.version,
            f"cat:{derived_category}",
        )
    for rule_id, domain, pattern in t.policy_keywords:
        if pattern.search(name):
            return DomainResult(domain, "derived", "derived-low", t.version, rule_id)
    return DomainResult(t.default, "unmapped", "unmapped", t.version)


def suggest_domain(text: str) -> str | None:
    """Keyword suggestion shown in the review queue (never applied automatically)."""
    for _, domain, pattern in load_taxonomy().policy_keywords:
        if pattern.search(text):
            return domain
    return None


def frameworks_for(domain: str) -> dict[str, list[str]]:
    return load_taxonomy().crosswalk.get(domain, {})


def framework_family_label(framework: str, family: str) -> str:
    fw = load_taxonomy().frameworks.get(framework, {})
    return str(fw.get("families", {}).get(family, family))


def domains_in_family(framework: str, family: str) -> list[str]:
    return [d for d, m in load_taxonomy().crosswalk.items() if family in m.get(framework, [])]


@lru_cache
def _env_overrides(inline: str, file_path: str) -> tuple[DomainOverride, ...]:
    merged = list(parse_domain_overrides(inline))
    if file_path:
        merged = list(parse_domain_overrides(Path(file_path).read_text(encoding="utf-8"))) + merged
    return tuple(merged)


def configured_domain_overrides() -> tuple[DomainOverride, ...]:
    """Repo/env-managed overrides (ACD_DOMAIN_OVERRIDES[_FILE]); the fallback when the shared
    configuration gate is not enabled."""
    from app.config import get_settings

    s = get_settings()
    return _env_overrides(s.domain_overrides, s.domain_overrides_file)
