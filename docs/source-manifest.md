# Source manifest (I01)

Human-readable view of [`contracts/source-manifest.json`](../contracts/source-manifest.json). The JSON is authoritative; this page explains it.

Status: **draft, pending contract spike**. Research date 2026-10-21. Entries marked `UNVERIFIED`/`unverified` must be confirmed (read-only, separately authorized) before release. All identifiers in this repository are placeholders such as `00000000-0000-0000-0000-000000000000`.

## Principles

- Version-pinned allowlist, not a generic Azure proxy. Match on **method + host + path template + api-version**.
- A GET-only rule is wrong: Resource Graph and Policy Insights queries are read-only `POST`s. Those (and the optional Logs query) are flagged `readOnlyQueryPost`.
- Default deny. Evaluation triggers, remediation, provider registration, policy/extension/guest-assignment writes and guest code execution are explicitly denied (see the deny list in the JSON).
- Continuation links (`$skipToken`, `nextLink`) are followed only after validating host, scheme, scope relationship, path family and api-version; credentials are never sent to a link that fails validation. Paging must be exhausted or the result is recorded as partial.

## Sources

| Id | Method | Path (host `management.azure.com` unless noted) | api-version | Status | Paging | RBAC action (to verify) |
|---|---|---|---|---|---|---|
| arg-query | POST (query) | `/providers/Microsoft.ResourceGraph/resources` | 2024-04-01 | verified stable (research) | `$skipToken`, max 1000 | `Microsoft.ResourceGraph/resources/read` |
| policyinsights-querystates | POST (query) | `/subscriptions/{s}/providers/Microsoft.PolicyInsights/policyStates/latest/queryResults` | 2024-10-01 | **unverified** | nextLink/`$skiptoken` | `Microsoft.PolicyInsights/policyStates/queryResults/action` |
| policyinsights-summarize | POST (query) | `.../policyStates/latest/summarize` | 2024-10-01 | **unverified** | none | `Microsoft.PolicyInsights/policyStates/summarize/action` |
| policy-assignments-list | GET | `/subscriptions/{s}/providers/Microsoft.Authorization/policyAssignments` | 2023-04-01 | pinned pending spike | nextLink | `Microsoft.Authorization/policyAssignments/read` |
| policy-definitions-get | GET | `/providers/Microsoft.Authorization/policyDefinitions/{name}` | 2023-04-01 | pinned pending spike | nextLink (lists) | `Microsoft.Authorization/policyDefinitions/read` |
| policy-definition-versions-get | GET | `.../policyDefinitions/{name}/versions/{version}` | 2023-04-01 | **unverified** | nextLink (lists) | `.../policyDefinitions/versions/read` |
| policy-setdefinitions-get | GET | `/providers/Microsoft.Authorization/policySetDefinitions/{name}` | 2023-04-01 | pinned pending spike | nextLink (lists) | `Microsoft.Authorization/policySetDefinitions/read` |
| policy-exemptions-list | GET | `/subscriptions/{s}/providers/Microsoft.Authorization/policyExemptions` | 2022-07-01-preview | **unverified (preview/stable discrepancy)** | nextLink | `Microsoft.Authorization/policyExemptions/read` |
| guestconfig-assignments-vm / -arc | GET | `{V\|H}/providers/Microsoft.GuestConfiguration/guestConfigurationAssignments[/{name}]` | 2024-04-05 | verified stable (research) | nextLink | `Microsoft.GuestConfiguration/guestConfigurationAssignments/read` |
| guestconfig-reports-vm / -arc | GET | `{V\|H}/.../guestConfigurationAssignments/{name}/reports[/{reportId}]` | 2024-04-05 | verified stable (research) | nextLink | `.../guestConfigurationAssignments/reports/read` |
| arm-vm-get | GET | `{V}` and `{V}/extensions` | **unpinned** | unverified | nextLink (lists) | `Microsoft.Compute/virtualMachines/read`, `.../extensions/read` |
| arm-arc-machine-get | GET | `{H}` and `{H}/extensions` | **unpinned** | unverified | nextLink (lists) | `Microsoft.HybridCompute/machines/read`, `.../extensions/read` |
| authorization-permissions-rg | GET | `/subscriptions/{anchorSub}/resourcegroups/{anchorRG}/providers/Microsoft.Authorization/permissions` | 2022-04-01 | verified (reference page exists) | nextLink; all pages required | `Microsoft.Authorization/permissions/read` |
| defender-assessments (optional) | GET | `/subscriptions/{s}/providers/Microsoft.Security/assessments` | **unpinned** | unverified | nextLink | `Microsoft.Security/assessments/read` |
| logs-ingestion (optional sink) | POST (**sink write**) | `{dce}.ingest.monitor.azure.com/dataCollectionRules/{dcrId}/streams/{stream}` | 2023-01-01 | unverified | n/a | dataAction `Microsoft.Insights/Telemetry/Write` |
| logs-query (optional) | POST (query) | `api.loganalytics.azure.com/v1/workspaces/{id}/query` | v1 | unverified | n/a | dataAction `Microsoft.OperationalInsights/workspaces/query/read` |

Machine path prefixes: **V** = `/subscriptions/{s}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{vm}`; **H** = `/subscriptions/{s}/resourceGroups/{rg}/providers/Microsoft.HybridCompute/machines/{machine}`.

Notes on versions: a newer stable Policy API version (`2026-07-01`) exists per public docs; it was not evaluated here, so `2023-04-01` stays the working pin until the spike compares responses. RBAC action names are taken from the standard `*/read` convention and the research notes; **Reader must not be assumed to include every Policy Insights query action**, so an exact permission manifest test is required.

## Collector vs viewer

- Viewer requests use the current user's delegated (OBO) token and re-verify access per request.
- The scheduled collector uses a separate least-privilege read identity; it is never used to answer a viewer's authorization failure.

## Deny list (summary)

Policy evaluation triggers (`triggerEvaluation`), remediations, writes to policy assignments/definitions/initiatives/exemptions, guest assignment mutations, VM/Arc extension writes and agent installation, provider registration, `runCommand`, deployments/role-assignment writes as permission probes, and any host/path not in the manifest (including package content URIs). Negative tests must assert none are reachable.

## Open items for the contract spike

1. Confirm Policy Insights `2024-10-01` and the exact permission set for query/summarize.
2. Choose exemptions api-version (preview vs stable) with fixture tests.
3. Pin Compute, HybridCompute, Security, Logs Ingestion and Logs Query versions.
4. Confirm upstream Machine Configuration report retention and Azure-cloud availability.
5. Evaluate Policy `2026-07-01` differences.
