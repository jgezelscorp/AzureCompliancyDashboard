# Dashboard UI notes

## Security domains UI

The API behind these views is `/api/v1/domains/*` (see `security-domains.md` for the taxonomy and mapping layers).

**Overview (CISO)**
- *By security domain*: per domain, Azure Policy compliance % and the machine check pass rate are shown side by side with their denominators and grain. They are never merged into one score. A "How is this calculated?" popover explains the formulas. Each row links to the Explorer (`/explorer?tab=states&domain=...`) and the Technical view (`/technical?domain=...`).
- *By framework (indicative)*: distinct policy and check counts per framework family. Rows overlap, so they are not additive, and the panel always shows the disclaimer: indicative related controls, not compliance claims or certification.
- *Domain data quality*: provenance mix (override / source / derived / unmapped) for policies and checks, the unmapped share, and a link to the Needs-category queue.
- The trend shows a "Taxonomy changed" warning when the taxonomy version changed inside the window, because domain trends are then not strictly comparable.

**Explorer**
- Filter bar: *Security domain* and *Domain provenance* filters, persisted in the URL (`domain=`, `confidence=`). A domain drill shows a breadcrumb and a Back button; Escape does the same (as in the Technical view).
- *Needs category* tab: queue of policies and checks that are unmapped or low confidence, with kind, provenance and search filters, paging, a suggested domain and a one-click assignment (`POST /api/v1/domains/overrides`).
- *Overrides* tab: saved overrides with delete (`DELETE /api/v1/domains/overrides/{id}`).
- Assign and delete are enabled only when `/api/v1/auth/capabilities` allows editing shared configuration **and** the server reports `gateEnabled`. Otherwise the tab explains the fallback from the API's `editing` text (`ACD_DOMAIN_OVERRIDES` / `ACD_DOMAIN_OVERRIDES_FILE`).

**Provenance badges** always carry a text label (Override, Source category, Derived (high), Derived (low), Unmapped), not just a colour.

**Exports** of the domain panels, the policy states table, the Needs-category queue and the domain checks drill are client-side CSVs that match the screen: they include the domain and provenance columns and list the active domain filter. The server-side export jobs are unchanged.
