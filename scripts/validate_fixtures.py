"""Validate fixtures against contracts/schemas and assert golden counts. Plain python.

Run: python scripts/validate_fixtures.py   (requires: pip install jsonschema)
"""
import json
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from metrics_reference import compute

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "contracts" / "schemas"
FIXTURES = ROOT / "tests" / "fixtures"
GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# Only placeholders and the public built-in CIS definition ID are allowed GUIDs.
ALLOWED_GUIDS = {"6dcfa239-b481-4de9-a03f-980f24f3b0bb"}

errors = []


def check(cond, msg):
    if not cond:
        errors.append(msg)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    resources = []
    for p in sorted(SCHEMAS.glob("*.schema.json")):
        doc = load(p)
        Draft202012Validator.check_schema(doc)
        resources.append((p.name, Resource.from_contents(doc)))
        resources.append((doc["$id"], Resource.from_contents(doc)))
    registry = Registry().with_resources(resources)
    bundle_schema = load(SCHEMAS / "evidence-bundle.schema.json")
    validator = Draft202012Validator(bundle_schema, registry=registry)

    files = sorted(FIXTURES.glob("*.json"))
    check(files, "no fixtures found")
    data = {}
    for f in files:
        doc = load(f)
        data[f.name] = doc
        for e in validator.iter_errors(doc):
            errors.append(f"{f.name}: schema: {'/'.join(map(str, e.absolute_path))}: {e.message}")
        check(doc.get("synthetic") is True, f"{f.name}: missing synthetic marker")
        for g in GUID_RE.findall(f.read_text(encoding="utf-8")):
            check(g == "00000000-0000-0000-0000-000000000000" or g.startswith("00000000-0000-0000-0000-0000000000")
                  or g in ALLOWED_GUIDS, f"{f.name}: non-placeholder GUID {g}")
        for fam, exp in doc["expected"].items():
            check(compute(doc, fam) == exp, f"{f.name}: expected metrics for {fam} differ from reference")

    # Golden: observed Arc AzureWindowsBaseline shape.
    arc = data["arc-azurewindowsbaseline-373.json"]
    rep = arc["reports"][0]
    checks = rep["checks"]
    keys = {c["checkKey"] for c in checks}
    check(len(checks) == 373 and len(keys) == 373, f"arc: expected 373 unique checks, got {len(checks)}/{len(keys)}")
    comp = sum(c["complianceStatus"] == "Compliant" for c in checks)
    non = sum(c["complianceStatus"] == "NonCompliant" for c in checks)
    check((comp, non) == (109, 264), f"arc: expected 109/264, got {comp}/{non}")
    reasons = sum(len(c["reasons"]) for c in checks)
    check(reasons > non, f"arc: reasons ({reasons}) must exceed noncompliant checks ({non}) in this fixture")
    check(all(not c["reasons"] for c in checks if c["complianceStatus"] == "Compliant"), "arc: compliant check has reasons")
    m = arc["expected"]["AzureWindowsBaseline"]["checkPassRate"]
    check((m["passed"], m["failed"], m["total"]) == (109, 264, 373), "arc: metric counts wrong")

    # Golden: synthetic CIS.
    cis = data["cis-synthetic-mixed.json"]
    e = cis["expected"]["CISWindowsSecurityBaseline"]
    q = {x["machineId"].rsplit("/", 1)[1]: x for x in e["machines"]}
    check(q["vm-synth-01"]["green"] is True, "cis: fresh compliant should be green")
    check(q["arc-synth-02"]["green"] is False, "cis: noncompliant must not be green")
    check(q["vm-synth-03"]["evidenceQuality"] == "Stale" and not q["vm-synth-03"]["green"], "cis: stale must not be green")
    check(q["vm-synth-04"]["evidenceQuality"] == "MissingAssignment" and not q["vm-synth-04"]["green"], "cis: missing assignment green")
    check(q["arc-synth-05"]["evidenceQuality"] == "UnknownApplicability", "cis: unknown eligibility")
    check(q["vm-synth-06"]["evidenceQuality"] == "NoReport" and not q["vm-synth-06"]["green"], "cis: no report green")
    check(e["checkPassRate"]["total"] == 20 and e["checkPassRate"]["passed"] == 16, "cis: pass rate counts")
    check(e["checkPassRate"]["reportsExcludedAsNotFresh"] == 1, "cis: stale report must be excluded")
    check(e["coverage"]["eligible"] == 5 and e["coverage"]["unknownEligibility"] == 1, "cis: eligibility counts")
    check(e["coverage"]["freshReport"] == 2 and e["coverage"]["usableReport"] == 3, "cis: coverage counts")
    check(e["policyCompliance"]["percent"] == 66.67 and e["policyCompliance"]["exempt"] == 1, "cis: policy compliance")

    empty = data["empty-estate.json"]["expected"]
    for fam, ex in empty.items():
        check(ex["policyCompliance"]["percent"] is None and ex["checkPassRate"]["percent"] is None
              and ex["coverage"]["freshReportPercent"] is None, f"empty: {fam} ratios must be null")

    dual = data["dual-family-distinct.json"]["expected"]
    check(dual["AzureWindowsBaseline"]["machines"][0]["green"] is True, "dual: baseline green")
    check(dual["CISWindowsSecurityBaseline"]["machines"][0]["green"] is False
          and dual["CISWindowsSecurityBaseline"]["machines"][0]["evidenceQuality"] == "MissingAssignment",
          "dual: baseline evidence must not satisfy CIS")

    if errors:
        print("FAILED")
        for x in errors:
            print(" -", x)
        return 1
    print(f"OK: {len(files)} fixtures validated against schemas; golden counts asserted "
          f"(373 checks = {comp} Compliant + {non} NonCompliant; {reasons} reasons not counted as checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
