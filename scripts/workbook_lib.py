"""Assemble the Azure Workbook gallery JSON from the KQL sources in workbooks/queries.

Single source of truth: workbooks/queries/*.kql (+ _fragments/*.kql). The generated
workbooks/azure-compliance.workbook.json is checked in and verified to be up to date by CI.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUERY_DIR = ROOT / "workbooks" / "queries"
FRAGMENT_DIR = QUERY_DIR / "_fragments"
WORKBOOK_PATH = ROOT / "workbooks" / "azure-compliance.workbook.json"
# Bicep loadTextContent is capped at 131072 chars per file; the deployed JSON is loaded as two parts.
PART_DIR = ROOT / "workbooks" / "parts"
PART_PATHS = [PART_DIR / "azure-compliance.part1.txt", PART_DIR / "azure-compliance.part2.txt"]
BICEP_LOAD_LIMIT = 131072


TABS = [
    ("overview", "Overview / CISO"),
    ("policy", "Policy estate"),
    ("baselines", "Baselines"),
    ("categories", "Categories"),
    ("checks", "Check / reason detail"),
    ("machines", "Machines"),
    ("evidence", "Evidence & limitations"),
    ("history", "History / Enhanced (Log Analytics)"),
]

# Workbook parameters a query may reference; anything else is a bug.
KNOWN_PARAMETERS = {
    "Subscriptions", "ResourceGroups", "CisDefinitionId", "AzureBaselineDefinitionId",
    "Family", "Category", "CheckKey", "MachineId", "Workspace", "TimeRange",
}
# Parameters that queries must not interpolate into KQL text (they only drive the query scope).
SCOPE_ONLY_PARAMETERS = {"Workspace", "TimeRange"}
LOGS_TABLES = {
    "ComplianceCollectionRuns_CL", "PolicyComplianceSnapshots_CL",
    "MachineConfigReports_CL", "MachineConfigChecks_CL",
}
# Replaced by Bicep (replace()) with the optional workspace resource id parameter; empty means unset.
DEFAULT_WORKSPACE_TOKEN = "__DEFAULT_WORKSPACE_RESOURCE_ID__"
LOGS_WORKSPACE_TYPE = "microsoft.operationalinsights/workspaces"
TIME_RANGE_DEFAULT_MS = 2592000000
TIME_RANGE_CHOICES_MS = [86400000, 604800000, 2592000000, 7776000000, 31536000000, 34560000000]

INCLUDE = re.compile(r"^\s*//#include\s+(\w+)\s*$")
HEADER = re.compile(r"^// @(\w+)\s*(.*)$")

INTRO = (
    "# Azure Policy and Machine Configuration compliance (live)\n\n"
    "Live view from Azure Resource Graph using **your** Azure identity and the selected scope. "
    "This workbook is read-only and reports Azure Policy / Machine Configuration results; it is "
    "**not** a CIS (or any other) certification or attestation.\n\n"
    "Three different measures are always shown separately and never blended: **Azure Policy "
    "compliance %**, **check pass rate** and **coverage**. Stale, unknown-age, missing or "
    "no-data evidence is never shown as compliant.\n\n"
    "All tabs except **History / Enhanced** are live and need nothing but Azure RBAC read access. "
    "The History tab is optional: it reads stored snapshots from a Log Analytics workspace that "
    "the standalone collector fills, and works only when that workspace is selected."
)

OVERVIEW_DEFINITIONS = (
    "### Metric definitions\n\n"
    "| Measure | Numerator / denominator | Grain |\n|---|---|---|\n"
    "| Azure Policy compliance % | Compliant / (Compliant + NonCompliant); Exempt and other states are counted apart | policy state row (resource x assignment) |\n"
    "| Check pass rate | unique checks Compliant / unique checks total, Fresh reports only | check (reasons are not checks) |\n"
    "| Coverage | eligible machines with assignment / usable report / fresh report, over Windows-eligible machines | machine x family |\n"
    "| Green machine | evidence Fresh (report endTime within 24h) AND reported state Compliant | machine x family |\n\n"
    "A ratio with a zero denominator is shown as no data, never 0% or 100%."
)

POLICY_TEXT = (
    "### Policy estate (all resources)\n\n"
    "Live Azure Policy state rows from Resource Graph for every assigned policy, not only Machine "
    "Configuration. Percent = Compliant / (Compliant + NonCompliant); Exempt and other states are "
    "shown apart. Counts are state rows and can differ from the standalone app, which stores the "
    "Policy Insights latest-state API result. Exemptions are on the Evidence tab."
)

EVIDENCE_TEXT = (
    "### Evidence and limitations\n\n"
    "- **Live tabs only show the latest state.** Resource Graph holds the latest indexed state. There is no durable history, "
    "so no posture trend is shown on them. Stored snapshots need the enhanced mode (History tab, Log Analytics) or the standalone app.\n"
    "- **Resource Graph is a projection.** It can lag, scrubs some data and is not guaranteed to expose "
    "every report property (completeness, expected/actual values, history). Verify against the Machine "
    "Configuration report for a selected machine.\n"
    "- **Fresh** means the report endTime is within 24 hours of the time the query runs; older is Stale, "
    "a missing time is UnknownAge. Neither is ever treated as passing.\n"
    "- **Reasons are not checks.** One check can carry several reasons; only unique check keys are counted.\n"
    "- **Native CIS Windows Server is a preview offering with unverified applicability.** Missing CIS "
    "assignments are 'assessment unavailable', not failures and not compliance. AzureWindowsBaseline and "
    "CISWindowsSecurityBaseline are separate families; a cross-reference is not equivalence.\n"
    "- **No certification claim.** Categories are the source category when the report provides one, "
    "otherwise an **app-derived heuristic grouping** of the check name (app rules v__RULES_VERSION__, laid out like "
    "the public Microsoft Windows security baseline groups). It is not a benchmark mapping; unmatched "
    "checks stay 'Uncategorized'. The same rules drive the standalone app. No "
    "benchmark control mapping is asserted without verified provenance.\n"
    "- **Scope and permissions.** Results contain only what your Azure RBAC allows; parameters filter the "
    "view but are not authorization. Row counts above Resource Graph limits (1,000 rows per page in the "
    "portal grid, expansion limits) can truncate results; narrow the scope if a grid reports truncation."
)


HISTORY_TEXT = (
    "### History / Enhanced mode (optional, Log Analytics)\n\n"
    "This tab reads **stored snapshots** that the standalone collector delivered to a Log Analytics "
    "workspace. It is not live: every value is as of the collector snapshot time shown in the first "
    "table, and **delivery lag** (ingestion time minus snapshot time) shows how far behind the "
    "workspace is. Compare with the live tabs, which query Azure directly.\n\n"
    "- Select the **Log Analytics workspace** and **Time range** in the parameters above. The "
    "subscription and resource-group filters do **not** scope this tab: log rows are filtered by "
    "workspace access, not by those parameters. Access to the workspace is not authorization for "
    "the underlying Azure resources; use resource-context access or one workspace per security "
    "boundary.\n"
    "- History starts when the collector first delivered data and can have gaps (collector or "
    "delivery outages). Missing rows are shown as missing, never inferred.\n"
    "- Interactive history covers up to 13 calendar months when the tables were deployed with the "
    "provided retention setting.\n"
    "- Results describe Azure Policy / Machine Configuration reports; they are not a CIS "
    "certification."
)

HISTORY_NO_WORKSPACE = (
    "**No Log Analytics workspace selected.** Choose one in the *Log Analytics workspace* "
    "parameter to see history. The History tab is optional; every other tab works without it."
)


def read_text(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


CATEGORY_RULES_PATH = ROOT / "backend" / "app" / "domain" / "check_categories.json"
CATEGORY_TOKEN = re.compile(r"__CATEGORY_CASE\((\w+)\)__")


def category_rules():
    return json.loads(CATEGORY_RULES_PATH.read_text(encoding="utf-8"))


def category_case(expr):
    """KQL case() equivalent of the shared ordered rules (first match wins).

    Same data file as backend/app/domain/check_categories.json, so workbook and app cannot drift.
    Patterns use RE2 syntax with an (?i) flag; they are emitted as KQL verbatim strings.
    """
    data = category_rules()
    parts = []
    for rule in data["rules"]:
        pattern = rule["pattern"]
        if "'" in pattern:
            raise ValueError(f"rule {rule['id']}: single quote not allowed in a workbook pattern (use \\x27)")
        parts.append(f"{expr} matches regex @'(?i){pattern}', '{rule['category']}'")
    if len(parts) > 30:
        raise ValueError("too many category rules for a KQL case() expression")
    return "case(" + ", ".join(parts) + f", '{data['defaultCategory']}')"


DOMAIN_TAXONOMY_PATH = ROOT / "backend" / "app" / "domain" / "domain_taxonomy.json"
DOMAIN_TOKEN = re.compile(r"__DOMAIN_CASE\((\w+),\s*(\w+)\)__")


def domain_taxonomy():
    return json.loads(DOMAIN_TAXONOMY_PATH.read_text(encoding="utf-8"))


def domain_case(cat_expr, name_expr):
    """KQL case() equivalent of the policy domain classifier (override layer is app-only).

    Arms yield 'domain|provenance'. Source category (exact, case-insensitive) wins over display-name
    keywords (derived-low); everything else is 'other|unmapped'. Same data file as the backend.
    """
    data = domain_taxonomy()
    by_domain = {}
    for category, domain in data["policyCategoryMap"].items():
        if "'" in category:
            raise ValueError(f"category {category!r}: single quote not allowed")
        by_domain.setdefault(domain, []).append(category)
    parts = []
    for domain, cats in by_domain.items():
        listed = ",".join(f"'{c}'" for c in cats)
        parts.append(f"{cat_expr} in~ ({listed}),'{domain}|source'")
    for rule in data["policyKeywordRules"]:
        if "'" in rule["pattern"]:
            raise ValueError(f"rule {rule['id']}: single quote not allowed")
        parts.append(f"{name_expr} matches regex @'(?i){rule['pattern']}','{rule['domain']}|derived-low'")
    return "case(" + ",".join(parts) + f",'{data['defaultDomain']}|unmapped')"


def render_category_tokens(text):
    version = str(category_rules()["rulesVersion"])
    text = DOMAIN_TOKEN.sub(lambda m: domain_case(m.group(1), m.group(2)), text)
    text = text.replace("__TAXONOMY_VERSION__", str(domain_taxonomy()["taxonomyVersion"]))
    return CATEGORY_TOKEN.sub(lambda m: category_case(m.group(1)), text).replace(
        "__RULES_VERSION__", version
    )


def load_fragments():
    """Fragments may include other fragments. Resource Graph has no `let`, so includes are textual."""
    raw = {p.stem: read_text(p).rstrip("\n") for p in sorted(FRAGMENT_DIR.glob("*.kql"))}

    def expand(name, seen=()):
        if name in seen:
            raise ValueError(f"circular fragment include: {name}")
        lines = []
        for line in raw[name].splitlines():
            inc = INCLUDE.match(line.strip())
            lines.append(expand(inc.group(1), seen + (name,)) if inc else line)
        return "\n".join(lines)

    return {name: expand(name) for name in raw}


def parse_query(path, fragments):
    meta = {"notes": [], "exports": [], "viz": "table", "nodata": "No data.", "source": "arg"}
    body = []
    for line in read_text(path).splitlines():
        inc = INCLUDE.match(line)
        if inc:
            body.append(fragments[inc.group(1)])
            continue
        head = HEADER.match(line)
        if head:
            key, value = head.group(1), head.group(2).strip()
            if key == "note":
                meta["notes"].append(value)
            elif key == "export":
                field, param = value.split("=")
                meta["exports"].append((field, param))
            else:
                meta[key] = value
            continue
        body.append(line)
    meta["query"] = render_category_tokens("\n".join(body).strip() + "\n")
    meta["notes"] = [render_category_tokens(n) for n in meta["notes"]]
    meta["file"] = path.name
    return meta


def load_queries():
    fragments = load_fragments()
    return [parse_query(p, fragments) for p in sorted(QUERY_DIR.glob("*.kql"))]


def _visible(tab):
    return {"parameterName": "tab", "comparison": "isEqualTo", "value": tab}


def _logs_visible(tab):
    """History items need the tab AND a selected workspace (all conditions must hold)."""
    return [
        _visible(tab),
        {"parameterName": "Workspace", "comparison": "isNotEqualTo", "value": ""},
    ]


def _markdown(name, text, tab=None):
    item = {"type": 1, "content": {"json": text}, "name": name}
    if tab:
        item["conditionalVisibility"] = _visible(tab)
    return item


def _compact_kql(text):
    """Single-line KQL (no comments or multi-line strings in our queries) to save serialized size."""
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def _query_item(q, viz=None, suffix="", with_exports=True):
    logs = q["source"] == "logs"
    content = {
        "version": "KqlItem/1.0",
        "query": _compact_kql(q["query"]),
        "size": 1,
        "title": q["title"] + suffix,
        "noDataMessage": q["nodata"],
        "queryType": 0 if logs else 1,
        "resourceType": LOGS_WORKSPACE_TYPE if logs else "microsoft.resourcegraph/resources",
        "crossComponentResources": ["{Workspace}"] if logs else ["{Subscriptions}"],
        "visualization": viz or "table",
        "gridSettings": {"filter": True},
    }
    if logs:
        content["timeContext"] = {"durationMs": TIME_RANGE_DEFAULT_MS}
        content["timeContextFromParameter"] = "TimeRange"
    if viz == "barchart":
        content["chartSettings"] = {"showLegend": True}
    if with_exports and q["exports"]:
        content["gridSettings"]["rowLimit"] = 1000
        content["exportedParameters"] = [
            {"fieldName": f, "parameterName": p, "parameterType": 1} for f, p in q["exports"]
        ]
    item = {
        "type": 3,
        "content": content,
        "name": f"query - {q['id']}{'-table' if suffix else ''}",
    }
    if logs:
        item["conditionalVisibilities"] = _logs_visible(q["tab"])
    else:
        item["conditionalVisibility"] = _visible(q["tab"])
    return item


def _tab_notes(tab, source, group):
    """One notes block per tab (and data source) keeps the workbook under the ARM expression limit."""
    text = "**Query assumptions**\n" + "\n".join(
        f"- **{q['title']}**\n" + "\n".join(f"  - {n}" for n in q["notes"]) for q in group
    )
    item = _markdown(f"notes - {tab}-{source}", text, tab)
    if source == "logs":
        del item["conditionalVisibility"]
        item["conditionalVisibilities"] = _logs_visible(tab)
    return item


def _parameters():
    def text(name, label, default, desc):
        return {
            "id": f"param-{name}", "version": "KqlParameterItem/1.0", "name": name, "label": label,
            "type": 1, "isRequired": True, "value": default, "isGlobal": True,
            "description": desc,
        }

    return {
        "type": 9,
        "content": {
            "version": "KqlParameterItem/1.0",
            "parameters": [
                {
                    "id": "param-Subscriptions", "version": "KqlParameterItem/1.0",
                    "name": "Subscriptions", "label": "Subscriptions", "type": 6,
                    "isRequired": True, "multiSelect": True, "quote": "'", "delimiter": ",",
                    "typeSettings": {"additionalResourceOptions": ["value::all"], "includeAll": True,
                                     "showDefault": False},
                    "defaultValue": "value::all", "isGlobal": True,
                },
                {
                    "id": "param-ResourceGroups", "version": "KqlParameterItem/1.0",
                    "name": "ResourceGroups", "label": "Resource groups", "type": 2,
                    "isRequired": True, "multiSelect": True, "quote": "'", "delimiter": ",",
                    "selectAllValue": "*", "defaultValue": "value::all",
                    "queryType": 1, "resourceType": "microsoft.resourcegraph/resources",
                    "crossComponentResources": ["{Subscriptions}"],
                    "query": "resourcecontainers\n| where type =~ 'microsoft.resources/subscriptions/resourcegroups'\n"
                             "| distinct name\n| project value = tolower(name), label = name\n| order by label asc",
                    "typeSettings": {"additionalResourceOptions": ["value::all"], "showDefault": False},
                    "isGlobal": True,
                },
                {
                    "id": "param-Family", "version": "KqlParameterItem/1.0", "name": "Family",
                    "label": "Baseline family", "type": 2, "isRequired": True, "value": "*",
                    "isGlobal": True, "queryType": 8,
                    "jsonData": json.dumps([
                        {"value": "*", "label": "All families (shown separately)"},
                        {"value": "AzureWindowsBaseline", "label": "AzureWindowsBaseline"},
                        {"value": "CISWindowsSecurityBaseline", "label": "CISWindowsSecurityBaseline (native CIS, preview)"},
                    ]),
                    "typeSettings": {"additionalResourceOptions": [], "showDefault": False},
                },
                {
                    "id": "param-Workspace", "version": "KqlParameterItem/1.0", "name": "Workspace",
                    "label": "Log Analytics workspace (History tab, optional)", "type": 5,
                    "isRequired": False, "multiSelect": False, "value": DEFAULT_WORKSPACE_TOKEN,
                    "queryType": 1, "resourceType": "microsoft.resourcegraph/resources",
                    "crossComponentResources": ["{Subscriptions}"],
                    "query": "resources\n| where type =~ 'microsoft.operationalinsights/workspaces'\n"
                             "| project value = id, label = name\n| order by label asc",
                    "typeSettings": {"additionalResourceOptions": [], "showDefault": False},
                    "isGlobal": True,
                },
                {
                    "id": "param-TimeRange", "version": "KqlParameterItem/1.0", "name": "TimeRange",
                    "label": "Time range (History tab)", "type": 4, "isRequired": True,
                    "value": {"durationMs": TIME_RANGE_DEFAULT_MS}, "isGlobal": True,
                    "typeSettings": {
                        "selectableValues": [{"durationMs": ms} for ms in TIME_RANGE_CHOICES_MS],
                        "allowCustom": True,
                    },
                },
                text("CisDefinitionId", "Native CIS policy definition GUID",
                     "6dcfa239-b481-4de9-a03f-980f24f3b0bb",
                     "Built-in policy definition GUID used only to label policy state rows as native CIS."),
                text("AzureBaselineDefinitionId", "Azure Windows baseline policy definition GUID",
                     "72650e9f-97bc-4b2a-ab5f-9781a9fcecbc",
                     "Built-in policy definition GUID 'Windows machines should meet requirements of the "
                     "Azure compute security baseline'; used only to label policy state rows."),
                dict(text("Category", "Selected category", "-", "Set by selecting a category row."),
                     isHiddenParameter=True),
                dict(text("CheckKey", "Selected check", "-", "Set by selecting a check row."),
                     isHiddenParameter=True),
                dict(text("MachineId", "Selected machine", "-", "Set by selecting a machine row."),
                     isHiddenParameter=True),
                {
                    "id": "param-tab", "version": "KqlParameterItem/1.0", "name": "tab", "type": 1,
                    "isRequired": True, "value": "overview", "isHiddenParameter": True,
                    "isGlobal": True,
                },
            ],
            "style": "pills",
            "queryType": 1,
            "resourceType": "microsoft.resourcegraph/resources",
        },
        "name": "parameters",
    }


def _tabs():
    return {
        "type": 11,
        "content": {
            "version": "LinkItem/1.0",
            "style": "tabs",
            "links": [
                {
                    "id": f"tab-{key}", "cellValue": "tab", "linkTarget": "parameter",
                    "linkLabel": label, "subTarget": key, "preText": "", "style": "link",
                }
                for key, label in TABS
            ],
        },
        "name": "tabs",
    }


def build_workbook():
    queries = load_queries()
    items = [_markdown("intro", INTRO), _parameters(), _tabs()]
    intro_by_tab = {"overview": OVERVIEW_DEFINITIONS, "policy": POLICY_TEXT, "history": HISTORY_TEXT}
    for key, _label in TABS:
        if key in intro_by_tab:
            items.append(_markdown(f"intro - {key}", intro_by_tab[key], key))
        if key == "evidence":
            items.append(_markdown("evidence - limitations", render_category_tokens(EVIDENCE_TEXT), key))
        if key == "history":
            no_ws = _markdown("history - no workspace", HISTORY_NO_WORKSPACE)
            no_ws["conditionalVisibilities"] = [
                _visible(key), {"parameterName": "Workspace", "comparison": "isEqualTo", "value": ""},
            ]
            items.append(no_ws)
        for q in (x for x in queries if x["tab"] == key):
            chart = q["viz"].startswith("barchart")
            items.append(_query_item(q, "barchart" if chart else "table", with_exports=not chart))
            if chart:
                items.append(_query_item(q, "table", " (table view)", with_exports=False))
        for source in ("arg", "logs"):
            group = [x for x in queries if x["tab"] == key and x["source"] == source]
            if group:
                items.append(_tab_notes(key, source, group))
    return {
        "version": "Notebook/1.0",
        "items": items,
        "fallbackResourceIds": [],
        "$schema": "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json",
    }


def split_parts(text):
    """Cut the compact JSON between two top-level items so each part stays under the Bicep limit."""
    cut = text.find('},{"type":', len(text) // 2) + 2
    return [text[:cut], text[cut:]]


def render(workbook):
    # Compact: the generated JSON must stay under Bicep's 131072-character loadTextContent limit.
    return json.dumps(workbook, ensure_ascii=False, separators=(",", ":")) + "\n"
