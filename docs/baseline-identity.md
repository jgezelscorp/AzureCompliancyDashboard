# Baseline identity and evidence gates (I01)

Two Machine Configuration baseline families are distinct package families and are never merged:

| Family | Guest configuration name | Source |
|---|---|---|
| Azure Windows security baseline | `AzureWindowsBaseline` | Azure-owned built-in policy definition (Guest Configuration category) |
| Native CIS Windows Server | `CISWindowsSecurityBaseline` | Azure-owned built-in policy definition below |

## Native CIS definition identity (verified from Azure-owned definition, 2026-10-21 research)

| Dimension | Value |
|---|---|
| Display name | `[Preview]: Center for Internet Security (CIS) Benchmarks for Windows Server` |
| Definition ID | `/providers/Microsoft.Authorization/policyDefinitions/6dcfa239-b481-4de9-a03f-980f24f3b0bb` |
| Definition version fetched | `1.0.1-preview` (built-in, category Guest Configuration) |
| Guest configuration name | `CISWindowsSecurityBaseline` |
| Guest configuration version selector | `1.*` (a selector, **not** a resolved package version) |
| Settings mapping | `BaselineSettings` -> `CISWindowsSecurityBaseline;BaselineSettings` |
| Effects | `AuditIfNotExists` or `Disabled` |
| Arc selection | `IncludeArcMachines`, documented default `"false"`; inspect actual assignment parameters |

The public built-in catalog lists the same ID with an older display name ("Official CIS Security Benchmarks for Windows Server") and version `1.0.0-preview`. This is a catalog discrepancy, **not** a second assessment: always identify by **definition ID + effective version + guest configuration metadata**, never by display text.

Decision: consume the existing native Azure Policy Machine Configuration assignment and its reports. Do not install, run or substitute a separate scanner or OSConfig assessment; no remediation; no baseline deployment.

## Applicability: what is and is not established

- Microsoft's initial-preview guidance documents Windows Server 2025, benchmark 1.0.0, profiles L1 Member Server and L1 Domain Controller, audit only; Server 2019/2022 "coming soon".
- The definition's targeting predicates are **broader** (Windows image/OS predicates, MicrosoftWindowsServer SKUs excluding `2008*`, opted-in Arc, and others). Predicates are targeting, not proof of package support.
- Neither source proves which OS/build/profile a given resolved package supports. Therefore: do not claim universal Server-2025-only support, do not claim universal support, and do not discard observed reports or hide older-server inventory.
- Baseline (`AzureWindowsBaseline`) mappings are Microsoft cross-references, not equivalence to a complete CIS assessment, and are never presented as verified CIS evidence.

Display state until resolved: **"native CIS applicability unverified"**. A missing assignment/report is not "unsupported", "compliant" or a failed control. Unsupported OS/profile/package combinations show "assessment unavailable", never compliant.

## Identity fields to record per assignment/report

Definition ID and effective version; policy assignment parameters (incl. `IncludeArcMachines`); guest configuration name and resolved version; sanitized content URI identity and content hash; `assignmentHash` and `parameterHash`; OS edition/build; CIS benchmark version and profile (when evidenced); report configuration identity; source URL/revision. Do not auto-fetch package content URLs.

## Evidence gates (all unresolved items stay blocked, not guessed)

| Gate | Owner | Pass condition |
|---|---|---|
| G-ID | Azure | Effective definition/version/parameters resolved by ID for the target scope |
| G-PKG | Azure + Backend | Resolved package version/hash/URI identity captured for Azure VM and Arc via assignment + report GET (api-version 2024-04-05), read-only and separately authorized |
| G-APP | Azure | Authoritative package applicability (OS/build/profile) obtained; otherwise stays "unverified" |
| G-SHAPE | Backend + Tester | Sanitized actual CIS report fixtures verify expected/actual/category/severity extraction; until then generic report rendering only, with explicit "unavailable" values |
| G-MAP | Azure | Control mappings (package check key -> benchmark/version/profile/control ID) carry provenance and verification status; unmapped remains unmapped |
| G-LIC | Azure + Lead | Licensing/provenance review before bundling any CIS benchmark text or package content; default to API-supplied identifiers/results and links |
| G-DIST | Tester | Baseline-only evidence is never shown as verified CIS; synthetic fixtures are labelled synthetic |

Observed Windows Azure baseline report evidence exists as the shape reference; equivalent CIS report-level evidence has **not** been verified.

## Out of scope

Automated remediation, baseline deployment/customization, new agent installation, a separate CIS scanner, and any ISO/NIS2/DORA/CIS certification claim.
