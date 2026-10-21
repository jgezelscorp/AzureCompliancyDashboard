"""Validate the live workbook: JSON structure, KQL sanity, public-repo hygiene, optional Bicep build.

Usage: python scripts/validate_workbook.py [--bicep]
Requires: pip install jsonschema. --bicep also runs `az bicep build` (or `bicep build`).
"""
import json
import re
import shutil
import subprocess
import sys

from jsonschema import Draft202012Validator

from workbook_lib import (
    KNOWN_PARAMETERS, ROOT, TABS, WORKBOOK_PATH, build_workbook, load_queries, render,
)

BICEP = ROOT / "infra" / "bicep" / "workbook" / "main.bicep"
BICEP_LOAD_LIMIT = 131072  # loadTextContent maximum file size
ALLOWED_TABLES = {"resources", "guestconfigurationresources", "policyresources", "resourcecontainers"}
FORBIDDEN_KQL = re.compile(r"\b(limit|take|sample|top)\b|^\s*\.|\bexternaldata\b|\bhttp_request\b|\bunion\s+\*", re.I | re.M)
GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# Public built-in native CIS policy definition id (docs/baseline-identity.md); not a tenant identifier.
ALLOWED_GUIDS = {"00000000-0000-0000-0000-000000000000", "6dcfa239-b481-4de9-a03f-980f24f3b0bb"}

WORKBOOK_SCHEMA = {
    "type": "object",
    "required": ["version", "items"],
    "properties": {
        "version": {"const": "Notebook/1.0"},
        "items": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/item"}},
    },
    "$defs": {
        "item": {
            "type": "object",
            "required": ["type", "content", "name"],
            "properties": {
                "type": {"enum": [1, 3, 9, 11]},
                "name": {"type": "string", "minLength": 1},
                "conditionalVisibility": {
                    "type": "object",
                    "required": ["parameterName", "comparison", "value"],
                },
            },
            "allOf": [
                {"if": {"properties": {"type": {"const": 1}}},
                 "then": {"properties": {"content": {"type": "object", "required": ["json"]}}}},
                {"if": {"properties": {"type": {"const": 3}}},
                 "then": {"properties": {"content": {
                     "type": "object",
                     "required": ["version", "query", "queryType", "resourceType", "crossComponentResources", "visualization"],
                     "properties": {
                         "version": {"const": "KqlItem/1.0"},
                         "queryType": {"const": 1},
                         "resourceType": {"const": "microsoft.resourcegraph/resources"},
                         "visualization": {"enum": ["table", "barchart"]},
                         "query": {"type": "string", "minLength": 10},
                     }}}}},
                {"if": {"properties": {"type": {"const": 9}}},
                 "then": {"properties": {"content": {
                     "type": "object", "required": ["parameters"],
                     "properties": {"parameters": {"type": "array", "items": {
                         "type": "object", "required": ["name", "type", "version"]}}}}}}},
                {"if": {"properties": {"type": {"const": 11}}},
                 "then": {"properties": {"content": {
                     "type": "object", "required": ["links"],
                     "properties": {"links": {"type": "array", "minItems": 1}}}}}},
            ],
        }
    },
}


def strip_strings(kql):
    kql = re.sub(r"@'[^']*'", "''", kql)
    kql = re.sub(r"'(?:[^'\\]|\\.)*'", "''", kql)
    return re.sub(r"//.*", "", kql)


def check_kql(q, errors):
    where = q["file"]
    text = q["query"]
    code = strip_strings(text)
    for open_, close in ("()", "[]"):
        if code.count(open_) != code.count(close):
            errors.append(f"{where}: unbalanced {open_}{close}")
    if text.count("'") % 2:
        errors.append(f"{where}: odd number of single quotes")
    if FORBIDDEN_KQL.search(code):
        errors.append(f"{where}: forbidden construct (limit/take/sample/top, control command, external data)")
    tables = set(re.findall(r"(?:^|=|\n)\s*(resources|guestconfigurationresources|policyresources|resourcecontainers)\b", code, re.I))
    if not tables:
        errors.append(f"{where}: does not read an allowed Resource Graph table")
    if not tables <= ALLOWED_TABLES:
        errors.append(f"{where}: table outside allow list {tables - ALLOWED_TABLES}")
    for name in re.findall(r"\{(\w+)\}", text):
        if name not in KNOWN_PARAMETERS:
            errors.append(f"{where}: unknown workbook parameter {{{name}}}")
    for stmt in re.findall(r"^let\s+\w+\s*=", text, re.M):
        pass
    lets = len(re.findall(r"^let\s", text, re.M))
    ends = len(re.findall(r";\s*$", text, re.M))
    if ends < lets:
        errors.append(f"{where}: a let statement is not terminated with ';'")
    if "{{" in text or "}}" in text:
        errors.append(f"{where}: unresolved include or template marker")
    for field in ("id", "tab", "title"):
        if not q.get(field):
            errors.append(f"{where}: missing @{field}")
    if not q["notes"]:
        errors.append(f"{where}: no documented assumptions (@note)")
    if q.get("tab") not in {k for k, _ in TABS}:
        errors.append(f"{where}: unknown tab {q.get('tab')}")
    return tables


def check_contract_constants(queries, errors):
    joined = "\n".join(q["query"] for q in queries)
    for needle, why in (
        ("ageSeconds <= 86400", "24h freshness threshold"),
        ("'UnknownApplicability'", "unknown eligibility quality"),
        ("'MissingAssignment'", "missing assignment quality"),
        ("arg_max(rank", "latest report per machine and family"),
        ("round(100.0 *", "percentage rounding"),
        ("real(null)", "zero denominator yields null"),
    ):
        if needle not in joined:
            errors.append(f"contract constant missing from queries: {why} ({needle})")
    for q in queries:
        if q["id"] == "ovw-checks" and "Fresh" not in q["query"]:
            errors.append("ovw-checks must be restricted to Fresh reports")


def main() -> int:
    errors = []
    queries = load_queries()
    ids = [q["id"] for q in queries]
    if len(ids) != len(set(ids)):
        errors.append("duplicate query ids")
    for q in queries:
        check_kql(q, errors)
    check_contract_constants(queries, errors)

    raw = WORKBOOK_PATH.read_text(encoding="utf-8")
    try:
        workbook = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"invalid JSON: {exc}")
        return 1
    for err in Draft202012Validator(WORKBOOK_SCHEMA).iter_errors(workbook):
        errors.append(f"workbook schema: {'/'.join(map(str, err.absolute_path))}: {err.message}")
    if raw.replace("\r\n", "\n") != render(build_workbook()):
        errors.append("workbook JSON is out of date; run python scripts/build_workbook.py")
    if len(raw) >= BICEP_LOAD_LIMIT:
        errors.append(f"workbook JSON exceeds Bicep loadTextContent limit ({len(raw)} >= {BICEP_LOAD_LIMIT})")

    params = {p["name"] for it in workbook["items"] if it["type"] == 9 for p in it["content"]["parameters"]}
    if not KNOWN_PARAMETERS <= params:
        errors.append(f"missing workbook parameters: {sorted(KNOWN_PARAMETERS - params)}")
    for it in workbook["items"]:
        exports = it["content"].get("exportedParameters", []) if it["type"] == 3 else []
        for e in exports:
            if e["parameterName"] not in params:
                errors.append(f"{it['name']}: exports undeclared parameter {e['parameterName']}")
    tab_values = {link["subTarget"] for it in workbook["items"] if it["type"] == 11 for link in it["content"]["links"]}
    if tab_values != {k for k, _ in TABS}:
        errors.append("tab links do not match the defined tabs")

    blob = raw + BICEP.read_text(encoding="utf-8") + "".join(q["query"] for q in queries)
    for guid in set(GUID.findall(blob)):
        if guid.lower() not in ALLOWED_GUIDS:
            errors.append(f"unexpected GUID in workbook sources: {guid}")
    if "loadTextContent('../../../workbooks/azure-compliance.workbook.json')" not in BICEP.read_text(encoding="utf-8"):
        errors.append("Bicep does not load the workbook JSON")

    if "--bicep" in sys.argv:
        cmd = ["az", "bicep", "build", "--file", str(BICEP), "--stdout"] if shutil.which("az") else ["bicep", "build", str(BICEP), "--stdout"]
        result = subprocess.run(cmd, capture_output=True, text=True, shell=sys.platform == "win32")
        if result.returncode != 0:
            errors.append(f"bicep build failed: {result.stderr.strip()[:500]}")
        else:
            template = json.loads(result.stdout[result.stdout.index("{"):])
            wb = [r for r in template["resources"] if "workbooks" in r["type"]] if isinstance(template["resources"], list) else []
            if not wb:
                errors.append("compiled template has no workbook resource")
            elif json.loads(template["variables"]["serializedData"]) != workbook:
                errors.append("serializedData does not match workbook JSON")

    if errors:
        print("workbook validation FAILED")
        for e in errors:
            print(f" - {e}")
        return 1
    print(f"workbook validation OK ({len(queries)} queries, {len(workbook['items'])} items)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
