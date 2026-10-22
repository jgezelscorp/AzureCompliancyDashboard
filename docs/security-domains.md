# Security domains: layered categorization

Every Azure Policy definition and every Machine Configuration check belongs to exactly one of nine fixed domains, so policy and machine results roll up in one "by domain" view. Data file: `backend/app/domain/domain_taxonomy.json` (current `taxonomyVersion` 2). The app, the API and the workbook generator all read this one file.

## Domains
Identity and access, Data protection and encryption, Network security, Logging and monitoring, Endpoint and OS hardening, Backup and resilience, Governance and compliance, Cost and tagging, Other.

## Layers and precedence
1. **Source**: the policy definition's own `metadata.category` (mapped through the category table). Checks have no source category today, so all checks are derived. Source wins over derived.
2. **Curated mapping**: category map, display-name keyword rules (policies without a category), and for checks rules v1 (`check_categories.json`) plus generic CIS leading section numbers (no benchmark text).
3. **Framework crosswalk**: domain to related CIS Controls v8 groups, NIST CSF 2.0 functions and ISO/IEC 27001:2022 Annex A themes. These are *indicative related controls*, not compliance claims or certification. A row counts once per domain; framework counts are distinct per family and are not additive across families.
4. **Assisted review**: the "Needs category" queue (Explorer tab, CISO data-quality tile) lists unmapped and derived-low items; assigning creates an override.
5. **Governance**: `domain_version` is stored with each categorized row. A version change triggers a recompute that touches only category columns, never raw evidence. Trend responses carry `taxonomyVersions`, `taxonomyChanged` and `taxonomyNote`, and the UI flags comparisons that span versions.

## Provenance and confidence
Provenance: `source`, `derived`, `override`, `unmapped`. Confidence: `override`, `source`, `derived-high`, `derived-low`, `unmapped`. Both are shown in the UI and are filterable. KPIs: unmapped % and the source/derived/override mix.

## Override workflow
Editing overrides is allowed only through the Azure-RBAC-anchored shared-settings gate (`ACD_AUTH_ANCHOR_SUBSCRIPTION_ID` / `ACD_AUTH_ANCHOR_RESOURCE_GROUP`). Custom app roles never grant edit. If the gate is not configured the API returns 403 and overrides come from the env/file fallback `ACD_DOMAIN_OVERRIDES` / `ACD_DOMAIN_OVERRIDES_FILE`. API overrides are exact-match, limited to 500; create and delete trigger a recompute.

## Endpoints
`/api/v1/domains/overview`, `/api/v1/domains/frameworks`, `/api/v1/domains/queue`, `/api/v1/domains/overrides` (GET/POST/DELETE), plus `domain` and `confidence` filters on the policy API. All are RBAC-scope filtered before aggregation.

## Workbook parity
`workbooks/queries/74-pol-domain.kql` embeds the same category case and keyword rules generated from the data file (`scripts/workbook_lib.py`). Parity is tested in `backend/tests/test_workbook_domain_parity.py`. Overrides and framework tags exist only in the app. The workbook JSON is near the ARM 131,072-character expression limit, so notes are grouped per tab and KQL is single-line; keep new queries compact.

## Limitations
Domains are heuristic reporting aids. Governance is large because Regulatory Compliance initiative policies map there. Domain exports are client-side CSV. No check-level history by domain exists yet (only estate snapshots store `byDomain`).
