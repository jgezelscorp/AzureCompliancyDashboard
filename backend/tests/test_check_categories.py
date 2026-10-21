import json
import re
from pathlib import Path

import pytest

from app.domain import categories as cat
from app.domain.categories import (
    derive_category,
    parse_overrides,
    resolve_category,
    rules_version,
)

GOLDEN = json.loads(
    (Path(__file__).parents[2] / "tests" / "golden" / "check-category-golden.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("item", GOLDEN, ids=[g["name"][:40] for g in GOLDEN])
def test_golden_names_derive_expected_category(item: dict[str, str | None]) -> None:
    assert derive_category(str(item["name"])) == item["category"]


def test_rules_are_ordered_regex_and_translatable() -> None:
    version, default, rules = cat.load_rules()
    assert version >= 1
    assert default == "Uncategorized"
    assert len(rules) <= 30  # KQL case() argument limit
    for r in rules:
        assert not re.search(r"\(\?[=!<]", r.pattern.pattern), "RE2 has no lookaround"


def test_precedence_override_source_derived_unmapped() -> None:
    name = "Account Lockout Duration"
    ov = parse_overrides('[{"type":"exact","pattern":"account lockout duration","category":"X"}]')
    assert resolve_category(name, "", None, ov).source == "override"
    assert resolve_category(name, "", None, ov).category == "X"
    src = resolve_category(name, "", "Vendor Cat")
    assert (src.category, src.source) == ("Vendor Cat", "source")
    der = resolve_category(name)
    assert (der.category, der.source, der.rule_version) == (
        "Account Policies",
        "derived",
        rules_version(),
    )
    um = resolve_category("zzz nothing matches this")
    assert (um.category, um.source) == ("Uncategorized", "unmapped")


def test_override_kinds_and_validation() -> None:
    ov = parse_overrides(
        '[{"type":"prefix","pattern":"Network access","category":"P"},'
        '{"type":"regex","pattern":"^zz.*","category":"R"}]'
    )
    assert resolve_category("Network access: Foo", "", None, ov).category == "P"
    assert resolve_category("zz thing", "", None, ov).category == "R"
    with pytest.raises(ValueError):
        parse_overrides('[{"type":"bogus","pattern":"a","category":"b"}]')
    with pytest.raises(ValueError):
        parse_overrides('{"not":"a list"}')
    assert parse_overrides("") == ()


def test_cis_section_numbers_map_generically() -> None:
    assert derive_category("1.1.1 anything") == "Account Policies"
    assert derive_category("2.2.5 anything") == "User Rights Assignment"
    assert derive_category("2.3.10.1 anything") == "Security Options"
    assert derive_category("9.1.1 anything") == "Windows Firewall"
    assert derive_category("17.2.1 anything") == "Audit Policy"
