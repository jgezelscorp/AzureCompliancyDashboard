# Authentication, authorization and onboarding (I04)

Azure RBAC is the only authorization system; there are no custom app roles. Design background: [rbac-configuration-design.md](rbac-configuration-design.md).

## Sign-in and token validation

- The React app signs users in with Entra ID authorization code + PKCE using the SPA app registration (`GET /api/v1/auth/config` returns the public, non-secret values).
- FastAPI validates every bearer token: RS256 signature against the tenant JWKS, issuer, audience (`api_client_id` or `api://<id>`), `tid`, `oid`, expiry and the delegated scope (`access_as_user`). Any failure is a 401.

## On-behalf-of (OBO)

Protected endpoints exchange the caller's API token for a delegated ARM token (`app/auth/obo.py`). The collector identity is never used to answer or retry a viewer's authorization. If OBO fails the request is denied (403).

## Authorization checks

`app/auth/permissions.py` calls `Microsoft.Authorization/permissions` (api-version 2022-04-01) with the viewer's token, follows all pages, and evaluates `actions`/`notActions` with wildcard semantics. Any error, incomplete paging or unexpected shape means **deny**.

- Per-subscription visibility: the viewer must hold the read actions listed in `contracts/permissions-manifest.json`.
- Shared config editing: requires `Microsoft.Resources/deployments/write` at the pinned anchor resource group (`ACD_AUTH_ANCHOR_SUBSCRIPTION_ID`, `ACD_AUTH_ANCHOR_RESOURCE_GROUP`). Unset anchor means denied. No write is ever sent as a probe.
- Deny assignments, conditions and PIM behaviour of the permissions API are **unverified** and gate production use (see the design doc's acceptance gate).

## Endpoints (`/api/v1`)

| Endpoint | Purpose |
|---|---|
| `GET /auth/config` | Public SPA sign-in values |
| `GET /auth/me` | Current principal |
| `GET /auth/capabilities` | `canEditSharedConfig` (fail closed) |
| `GET /onboarding/scopes` | Subscriptions visible to the viewer with read readiness |
| `POST /onboarding/scopes` | Register an onboarding scope; needs anchor authorization, a visible and readable subscription |
| `GET /onboarding/registered` | Registered subscription IDs |
| `GET /onboarding/collector` | Non-secret collector identity configuration |

Registered scopes are held in memory in this work package; durable persistence arrives with settings storage (I06).

## Configuration (placeholders only; see `.env.example`)

`ACD_AUTH_TENANT_ID`, `ACD_AUTH_API_CLIENT_ID`, `ACD_AUTH_API_CLIENT_SECRET` (secret, environment only), `ACD_AUTH_SPA_CLIENT_ID`, `ACD_AUTH_REQUIRED_SCOPE`, anchor settings above, and collector identity (`ACD_AUTH_COLLECTOR_MODE` = `managed_identity` | `service_principal` | `workload_identity`, `ACD_AUTH_COLLECTOR_CLIENT_ID`).

## Onboarding steps

1. Register an API app and a SPA app (redirect URI of the frontend); expose the `access_as_user` scope and grant the API delegated `user_impersonation` on Azure Service Management.
2. Create an isolated anchor resource group and assign its RBAC to the people who may administer the app.
3. Set the variables above, sign in, and register subscriptions from `/onboarding/scopes`.
4. Grant the collector identity only the read permissions in the [source manifest](source-manifest.md).

## Permission manifest

`contracts/permissions-manifest.json` lists every RBAC action the code references with a `verified` flag. A backend test fails if the code uses an action not listed. Entries with `verified: false` must be confirmed before release.
