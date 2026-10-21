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

TABS = [
    ("overview", "Overview / CISO"),
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
LOGS_WORKSPACE_TYPE = "microsoft.operationalinsights/workspaces"
TIME_RANGE_DEFAULT_MS = 2592000000
TIME_RANGE_CHOICES_MS = [86400000, 604800000, 2592000000, 7776000000, 31536000000, 34560000000]

INCLUDE = re.compile(r"^//#include\s+(\w+)\s*$")
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
    "- **No certification claim.** Categories come from the check identifier prefix when present. No "
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


def load_fragments():
    return {p.stem: read_text(p).rstrip("\n") for p in sorted(FRAGMENT_DIR.glob("*.kql"))}


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
    meta["query"] = "\n".join(body).strip() + "\n"
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


def _query_item(q, viz=None, suffix="", with_exports=True):
    logs = q["source"] == "logs"
    content = {
        "version": "KqlItem/1.0",
        "query": q["query"],
        "size": 1,
        "title": q["title"] + suffix,
        "noDataMessage": q["nodata"],
        "queryType": 0 if logs else 1,
        "resourceType": LOGS_WORKSPACE_TYPE if logs else "microsoft.resourcegraph/resources",
        "crossComponentResources": ["{Workspace}"] if logs else ["{Subscriptions}"],
        "visualization": viz or "table",
        "gridSettings": {"filter": True, "sortBy": []},
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


def _notes(q):
    text = "**Query assumptions**\n" + "\n".join(f"- {n}" for n in q["notes"])
    item = _markdown(f"notes - {q['id']}", text, q["tab"])
    if q["source"] == "logs":
        del item["conditionalVisibility"]
        item["conditionalVisibilities"] = _logs_visible(q["tab"])
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
                    "isRequired": False, "multiSelect": False, "value": "",
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
                     "00000000-0000-0000-0000-000000000000",
                     "Set to the GUID of the Azure Windows baseline policy definition in your estate; "
                     "the placeholder labels no rows."),
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
    intro_by_tab = {"overview": OVERVIEW_DEFINITIONS, "history": HISTORY_TEXT}
    for key, _label in TABS:
        if key in intro_by_tab:
            items.append(_markdown(f"intro - {key}", intro_by_tab[key], key))
        if key == "evidence":
            items.append(_markdown("evidence - limitations", EVIDENCE_TEXT, key))
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
            items.append(_notes(q))
    return {
        "version": "Notebook/1.0",
        "items": items,
        "fallbackResourceIds": [],
        "$schema": "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json",
    }


def render(workbook):
    return json.dumps(workbook, indent=1, ensure_ascii=False) + "\n"
