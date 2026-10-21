# Live Azure Workbook (I07)

A read-only Azure Workbook that reports Azure Policy and Machine Configuration results for Azure VMs and Azure Arc-enabled servers, from Azure Resource Graph (ARG) only. It runs with the portal user's own Azure identity; nothing is deployed to the monitored estate and no Azure data is written.

The workbook reports Azure Policy / Machine Configuration results. It does **not** certify CIS (or any other) compliance.

## Files

| Path | Purpose |
|---|---|
| `workbooks/queries/*.kql` | One ARG query per grid/chart. Header lines (`// @tab`, `// @title`, `// @note`, `// @export`) carry metadata and the documented assumptions. |
| `workbooks/queries/_fragments/*.kql` | Shared building blocks (`machines`, `assignments`, `evidence`, `checks`, `policy`) pulled in with `//#include`. |
| `workbooks/azure-compliance.workbook.json` | Generated gallery template (Notebook/1.0). Do not edit by hand; run `python scripts\build_workbook.py`. |
| `infra/bicep/workbook/main.bicep` | Deploys the template as a shared workbook (`Microsoft.Insights/workbooks`). |
| `scripts/validate_workbook.py` | Structure, KQL sanity, hygiene and Bicep checks (CI `bicep-workbook` job). |
| `tests/workbook/` | Parity test: KQL-equivalent logic vs `scripts/metrics_reference.py` on the golden fixtures. |

## Tabs

1. **Overview / CISO** - Azure Policy compliance %, check pass rate and coverage as three separate, labeled tables (numerator, denominator, null when the denominator is 0), evidence-quality breakdown, evidence-age distribution, inventory.
2. **Baselines** - `AzureWindowsBaseline` and native `CISWindowsSecurityBaseline` side by side, never merged; version cohorts.
3. **Categories** - category summary; selecting a row lists the checks in it.
4. **Check / reason detail** - unique checks with failing-machine counts; selecting a check lists its reasons per machine.
5. **Machines** - machine x family status with evidence-quality reason; selecting a row lists that machine's checks.
6. **Evidence & limitations** - written limitations and policy exemptions with expiry.

Parameters: **Subscriptions** (multi-select, default all you can read), **Resource groups** (multi-select, default all), **Baseline family**, and two policy-definition GUIDs used only to label policy rows (`CisDefinitionId` defaults to the documented built-in native CIS definition; `AzureBaselineDefinitionId` defaults to the placeholder `00000000-0000-0000-0000-000000000000` and **must be set** to the Azure Windows baseline definition GUID used in your estate, otherwise no policy row is labeled AzureWindowsBaseline). No tenant or subscription ID is stored anywhere.

## Metric rules (from `docs/metrics-spec.md`)

- Azure Policy compliance %, check pass rate and coverage are never blended.
- Fresh = latest report `endTime` within 24 h of query time. Stale, UnknownAge, NoReport, MissingAssignment and UnknownApplicability are never green; only Fresh + Compliant is green.
- Check pass rate counts unique check keys in Fresh reports; reasons are shown but never counted as checks. Stale reports are excluded and counted (`reportsExcludedAsNotFresh`).
- Coverage denominator is Windows-eligible machines; Unknown OS evidence is reported separately.
- Live mode has no history: the overview shows evidence age, **not** a trend. Trend needs stored snapshots (enhanced mode I08, or the app).

## Query reference and assumptions

| Query | Tables | Key assumptions |
|---|---|---|
| `ovw-policy` | `policyresources` (`microsoft.policyinsights/policystates`) | Latest indexed state only. Family from `properties.policyDefinitionId` ending in the configured GUID. Exempt/other excluded from the denominator. |
| `ovw-checks` | `guestconfigurationresources`, `resources` | Check = unique `latestAssignmentReport.resources[].resourceId`. Fresh reports only. Duplicate key keeps worst status. |
| `ovw-coverage` | same | Eligible = `osType` Windows (Azure VM `storageProfile.osDisk.osType`, Arc `properties.osType`). |
| `ovw-quality`, `ovw-age` | same | Quality is derived as in the spec; only qualities observable in ARG are produced. |
| `ovw-inventory` | `resources` | Type-based Azure VM vs Arc split; inventory is not coverage. |
| `base-compare`, `base-versions` | same | Version is `properties.guestConfiguration.version` only; benchmark version/profile are not inferred. |
| `cat-summary`, `cat-checks` | same | Category = leading `[Category]` of the check id, else `Uncategorized`. No control mapping. |
| `check-list`, `check-reasons` | same | Expected/actual have no universal field; reasons are shown as returned. |
| `machine-list`, `machine-checks` | same | Key is the lower-cased full ARM id, so duplicate names stay distinct. Arc vs VM by type. |
| `evidence-exemptions` | `policyresources` (`microsoft.authorization/policyexemptions`) | Indexing and property names unverified. |

Machine/assignment join: assignment `id` is split at `/providers/microsoft.guestconfiguration/` to get the machine id; where several assignments exist for a machine and family the one with the latest report time is used (`arg_max`). Machines are joined to the two families with a left outer join so unmatched inventory stays visible.

Every query is also annotated with its assumptions inside the workbook (a notes block under each grid).

## Deploy (not performed by this repository's CI)

Prerequisites: Reader on the subscriptions to report on (Resource Graph and policy/guest configuration reads); Workbook Contributor (or Contributor) on the target resource group to save the workbook.

**Bicep**

```powershell
az deployment group what-if -g <resource-group> -f infra\bicep\workbook\main.bicep
az deployment group create  -g <resource-group> -f infra\bicep\workbook\main.bicep `
  -p workbookDisplayName="Azure Policy and Machine Configuration compliance (live)"
```

The default workbook name is a GUID derived from the resource group, so redeploying updates the same workbook. Scope of the *data* is chosen with the workbook parameters at run time.

**Manual import**: Azure portal > Monitor > Workbooks > New > Advanced editor (`</>`) > Gallery Template, paste `workbooks\azure-compliance.workbook.json`, Apply, Save.

## Validate locally

```powershell
pip install jsonschema pytest
python scripts\build_workbook.py --check   # generated JSON is current
python scripts\validate_workbook.py --bicep
pytest tests\workbook
```

## Parity testing

No KQL engine runs in CI. `tests/workbook/kql_model.py` re-implements the queries' logic step by step (same grouping, `arg_max`, left join, null handling) over ARG-shaped rows built from the fixtures, and tests assert it equals `scripts/metrics_reference.py` for every fixture and both families (including the 373 / 109 / 264 golden report, empty estate, stale boundary, unknown age and duplicate machine names). Separate tests assert the KQL text carries the contract constants (86400 s, `arg_max(rank`, `real(null)`). This proves the logic, not that the KQL text parses or that live ARG exposes the same properties.

## Caveats and unverified items

Nothing here was run against Azure. Verify in a non-production scope before relying on it:

- ARG table, type and column names (`guestconfigurationresources` assignments, `properties.latestAssignmentReport.endTime/complianceStatus/resources`, `properties.guestConfiguration.name/version`, `policyresources` state columns incl. `properties.resourceGroup`, `policyexemptions` type and `expiresOn`) are taken from Microsoft documentation and samples and are unverified against a live tenant. If `latestAssignmentReport.endTime` is not projected, every report is UnknownAge (never green).
- ARG may return the latest report only, can lag, and is not guaranteed to include all check detail or expected/actual values; compare with the report GET for a selected machine.
- Workbook-specific constructs (tab links with `subTarget`, `'*' in ({ResourceGroups})` with `selectAllValue`, exported grid parameters, `queryType 8` static dropdown) follow common published workbook patterns but were not rendered in the portal. `Microsoft.Insights/workbooks@2023-06-01` was only checked by `bicep build`.
- A check key containing a single quote breaks the drill-down queries for that check.
- Results are capped by ARG paging (1,000 rows per grid page) and expansion limits; narrow the scope if truncation is reported. Joins use ARG-supported flavors only.
- The Azure baseline policy-definition GUID is not in the I01 manifest and must be configured. Native CIS applicability remains unverified (gate G-APP): no CIS control mapping or benchmark claim is made.
- Percentages are rounded by KQL `round`; Python uses banker's rounding, so a half-way value may differ in the last digit.
- Portal workbook access does not grant data access; users only see what Azure RBAC lets them read.
