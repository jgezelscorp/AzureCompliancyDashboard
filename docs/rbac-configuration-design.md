# Azure-RBAC-only configuration authorization design (I01)

Status: design, not implemented. No Azure application roles exist; Azure RBAC is the only authorization system.

## Goals

- Technical and CISO views are presentation modes over the **same authorized rows**. Neither grants extra data or administration.
- Shared (global) configuration editing is authorized by the caller's effective Azure permissions at a fixed **configuration anchor**.
- Fail closed whenever authorization cannot be established.

## Viewer authorization (summary)

- React uses Entra authorization-code + PKCE. FastAPI validates the API token (signature, issuer, audience, tenant, expiry, delegated scope). API scopes only enable calling the API.
- FastAPI obtains a delegated ARM token with on-behalf-of (OBO) to verify the current viewer's Azure access. The collector's credentials are never used to answer or retry a viewer's authorization failure.
- Every protected request intersects: configured scope, collected scope, and currently verified viewer read access per evidence type. Rows are filtered **before** aggregation; no collector-wide summaries or cached cross-scope trends are served. No reusable positive-authorization cache in the initial release.

## Configuration anchor

- A dedicated, isolated Azure resource group (the **anchor RG**) holds the authority for configuration editing, even if the application runs outside Azure. Customers manage its RBAC normally. Owner/Contributor on monitored subscriptions is not required to administer the app.
- The anchor (tenant, subscription, RG) is **pinned outside ordinary editable configuration**; it can only change through controlled re-onboarding (see below).

## Capability mapping

Shared-config read/edit/commit requires effective **`Microsoft.Resources/deployments/write` at the anchor RG**.

- Normally granted by Owner and Contributor; a customer-approved custom role may carry it without full Contributor.
- This is an explicit mapping of an Azure permission to an application action. It does not create a fictitious Azure provider operation or an app role.
- **No deployment or other write is ever executed as a permission probe.**

## Permission check

On every configuration read/edit/commit, with the viewer's OBO token:

`GET https://management.azure.com/subscriptions/{anchorSubscription}/resourcegroups/{anchorRG}/providers/Microsoft.Authorization/permissions?api-version=2022-04-01`

Rules:

1. Follow all pages (`nextLink`); incomplete paging => deny.
2. Evaluate only the approved operation against returned `actions`/`notActions` using tested wildcard/set semantics. `dataActions` are not substitutes. A 200 or an RG read alone is insufficient.
3. Any error, timeout, ambiguity or unsupported shape => deny.
4. No role-assignment enumeration, group-expansion engine, or home-made inheritance/PIM/deny evaluator.

## Critical acceptance gate

The reference documents the caller's permissions and pagination but its contract alone does not prove that deny assignments, conditions and PIM (active vs eligible/expired) are reflected for an external application's decision. Before enabling shared editing, Azure identity + Tester must prove the chosen check respects:

| Case | Expected |
|---|---|
| Owner / Contributor at anchor | allowed |
| Inherited grant from parent scope | allowed |
| Customer-approved custom role containing the capability | allowed |
| Reader at anchor | denied |
| Contributor only on a child resource | denied at anchor |
| Deny assignment covering the capability | denied |
| Condition not satisfied (where relevant) | denied |
| PIM eligible-but-inactive or expired | denied |
| Paging failure / endpoint error / ambiguous output | denied (fail closed) |

If the gate cannot be satisfied, **shared configuration editing stays disabled** pending a supported Azure authorization mechanism. Do not approximate grants and do not fall back to custom app roles.

## Global vs personal changes

- **Personal filters:** tenant-bound selections inside the viewer's already-authorized, globally configured scope. They never change collection, retention, credentials or other users' scope.
- **Global configuration:** subscriptions, schedule and retention. Requires fresh anchor authorization server-side; bounded inputs, CSRF protection as applicable, optimistic revision checks, audit records without secret values. Proposed subscriptions must be in the configured tenant and pass a separate collector read-readiness check (anchor admin rights are not evidence of source-data access).
- **Removing a subscription** immediately hides it from ordinary views/exports and stops collection; retained evidence stays isolated until retention purge.
- **Adding a subscription** starts new coverage; no fabricated backfill.

## Tenant / anchor change (controlled re-onboarding)

Not an editable text field. Requires current anchor authorization **and** successful authentication/authorization at the destination tenant's proposed anchor, approved consent/collector credentials, validated source scopes, and Azure ownership evidence for the destination. Pause collection, atomically switch the configuration revision, invalidate sessions/caches/exports, and retain old records under their original tenant boundary. Never relabel or merge old evidence.

## Collector identity

Separate application identity (certificate or federated credential preferred outside Azure) with only the read/query permissions in the [source manifest](source-manifest.md). Admin authorization never broadens collector grants. Exact permission manifest must be tested (Reader may lack Policy Insights query actions).

## Limits honestly stated

Azure propagation delay and token lifetime mean instantaneous revocation cannot be promised; already-downloaded content cannot be recalled.
