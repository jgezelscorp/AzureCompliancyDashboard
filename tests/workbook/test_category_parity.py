"""Parity: the category rules embedded in the generated workbook KQL == the backend categorizer.

The workbook JSON is generated from backend/app/domain/check_categories.json. This test parses
the generated case() expression back out of the workbook and evaluates it with Python regexes
over golden names, then compares with the app categorizer.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

from app.domain.categories import derive_category, rules_version  # noqa: E402
from workbook_lib import WORKBOOK_PATH, category_case, load_queries  # noqa: E402

GOLDEN = json.loads((ROOT / "tests" / "golden" / "check-category-golden.json").read_text(encoding="utf-8"))
ARM = re.compile(r"matches regex @'(?P<pattern>[^']*)', '(?P<category>[^']*)'")
DEFAULT = re.compile(r", '([^']*)'\)$")


def eval_case(expression, name):
    for m in ARM.finditer(expression):
        if re.search(m.group("pattern"), name):
            return m.group("category")
    return DEFAULT.search(expression).group(1)


def test_generated_case_matches_python_categorizer_on_golden():
    expr = category_case("checkKey")
    for item in GOLDEN:
        assert eval_case(expr, item["name"]) == (item["category"] or "Uncategorized"), item["name"]
        assert derive_category(item["name"]) == item["category"], item["name"]


def test_workbook_queries_embed_the_generated_case():
    queries = {q["file"]: q["query"] for q in load_queries()}
    assert category_case("checkKey") in queries["20-cat-summary.kql"]
    assert category_case("CheckName") in queries["62-hist-cat-summary.kql"]
    assert category_case("CheckName") in queries["64-hist-cat-trend.kql"]
    for text in queries.values():
        assert "__CATEGORY_CASE" not in text and "__RULES_VERSION__" not in text


def test_committed_workbook_json_contains_current_rules_version():
    text = WORKBOOK_PATH.read_text(encoding="utf-8")
    assert f"app rules v{rules_version()}" in text
    assert json.dumps(category_case("checkKey"))[1:-1] in text


def test_kql_restrictions_for_category_queries():
    for q in load_queries():
        if q["source"] == "arg":
            assert not re.search(r"^\s*let\b|toscalar", q["query"], re.M)
