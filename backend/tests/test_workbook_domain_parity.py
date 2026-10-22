"""Parity: the domain case() embedded in the workbook == the backend policy classifier.

The workbook KQL is generated from backend/app/domain/domain_taxonomy.json. The generated case()
expression is parsed back out of the workbook text and evaluated in Python over synthetic golden
inputs, then compared with app.domain.domains.classify_policy (without overrides, which are
app-only).
"""

import json
import re
import sys
from pathlib import Path

import pytest

from app.domain.domains import classify_policy, taxonomy_version

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from workbook_lib import (  # type: ignore[import-not-found]  # noqa: E402
    PART_PATHS,
    WORKBOOK_PATH,
    domain_case,
    load_queries,
)

GOLDEN = [
    ("Security Center", "Anything"),
    ("  key vault ", "Keys should have expiry"),
    ("Network", "Subnets should be private"),
    ("Tags", "Require a tag on resources"),
    ("Backup", None),
    ("Guest Configuration", "Audit Windows machines"),
    (None, "Virtual machines should enable backup"),
    (None, "Storage accounts should use customer-managed key"),
    (None, "Require MFA for owners"),
    (None, "Public network access should be disabled"),
    (None, "Diagnostic logs should be enabled"),
    (None, "Allowed locations"),
    (None, "Completely unrelated text"),
    ("Brand New Category", "Completely unrelated text"),
    ("Brand New Category", "Audit Linux machines"),
    ("Azure AI Services", "Cognitive thing"),
]


def eval_case(expression: str, category: str | None, name: str | None) -> tuple[str, str]:
    body = expression
    for m in re.finditer(r"cat in~ \((?P<list>[^)]*)\),'(?P<d>[^|']*)\|(?P<p>[^']*)'", body):
        cats = {c.strip("'").lower() for c in m.group("list").split("','")}
        cats = {c.strip("'") for c in cats}
        if category and category.strip().lower() in cats:
            return m.group("d"), m.group("p")
    for m in re.finditer(
        r"name matches regex @'(?P<pat>[^']*)','(?P<d>[^|']*)\|(?P<p>[^']*)'", body
    ):
        if name and re.search(m.group("pat"), name):
            return m.group("d"), m.group("p")
    tail = re.search(r",'([^|']*)\|([^']*)'\)$", body)
    assert tail
    return tail.group(1), tail.group(2)


@pytest.mark.parametrize(("category", "name"), GOLDEN)
def test_generated_case_matches_python_classifier(category: str | None, name: str | None) -> None:
    expr = domain_case("cat", "name")
    domain, provenance = eval_case(expr, category, name)
    py = classify_policy(category, name)
    assert (domain, provenance) == (py.domain, py.confidence)


def test_workbook_embeds_generated_domain_case_and_version() -> None:
    q = {x["file"]: x["query"] for x in load_queries()}["74-pol-domain.kql"]
    assert domain_case("defCategory", "defDisplay") in q
    assert "__DOMAIN_CASE" not in q and "__TAXONOMY_VERSION__" not in q
    note = f"taxonomy v{taxonomy_version()}"
    assert note in WORKBOOK_PATH.read_text(encoding="utf-8")


def test_domain_query_respects_arg_restrictions() -> None:
    q = {x["file"]: x["query"] for x in load_queries()}["74-pol-domain.kql"]
    assert not re.search(r"^\s*let\b|toscalar|mv-expand|\bkind\b(?!=)", q, re.M)
    assert "{ResourceGroups}" in q


def test_bicep_parts_reassemble_the_workbook_json() -> None:
    text = WORKBOOK_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    joined = "".join(p.read_text(encoding="utf-8").replace("\r\n", "\n") for p in PART_PATHS)
    assert joined == text
    assert all(len(p.read_text(encoding="utf-8")) < 131072 for p in PART_PATHS)
    json.loads(joined)
