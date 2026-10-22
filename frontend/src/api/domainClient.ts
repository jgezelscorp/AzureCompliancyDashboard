import { get, send } from "./client";
import type {
  Capabilities,
  DomainChecks,
  DomainOverview,
  Frameworks,
  Overrides,
  OverrideRequest,
  OverrideRow,
  Provenance,
  Queue,
  QueueParams,
  Taxonomy,
} from "./domainTypes";
import { policyQuery } from "./policyClient";
import type { Filters } from "./policyTypes";

const BASE = "/api/v1/domains";

export interface DomainApi {
  taxonomy(signal?: AbortSignal): Promise<Taxonomy>;
  overview(filters: Filters, signal?: AbortSignal): Promise<DomainOverview>;
  frameworks(filters: Filters, signal?: AbortSignal): Promise<Frameworks>;
  provenance(filters: Filters, signal?: AbortSignal): Promise<Provenance & { grain: string }>;
  queue(params: QueueParams, filters: Filters, signal?: AbortSignal): Promise<Queue>;
  checks(domain: string, page?: { limit?: number; offset?: number }, signal?: AbortSignal): Promise<DomainChecks>;
  overrides(signal?: AbortSignal): Promise<Overrides>;
  /** 403 unless the Azure-RBAC anchored shared-config gate permits the caller. */
  createOverride(body: OverrideRequest): Promise<OverrideRow>;
  deleteOverride(id: number): Promise<void>;
  capabilities(signal?: AbortSignal): Promise<Capabilities>;
}

export function createDomainApi(f?: typeof fetch): DomainApi {
  const call = <T>(path: string, signal?: AbortSignal) => get<T>(path, f, { auth: true, signal });
  return {
    taxonomy: (s) => call(`${BASE}/taxonomy`, s),
    overview: (flt, s) => call(`${BASE}/overview${policyQuery(flt)}`, s),
    frameworks: (flt, s) => call(`${BASE}/frameworks${policyQuery(flt)}`, s),
    provenance: (flt, s) => call(`${BASE}/provenance${policyQuery(flt)}`, s),
    queue: (p, flt, s) =>
      call(
        `${BASE}/queue${policyQuery({ ...flt, confidence: p.confidence }, { kind: p.kind, q: p.q, limit: p.limit, offset: p.offset })}`,
        s,
      ),
    checks: (domain, page, s) => call(`${BASE}/checks${policyQuery({}, { domain, ...page })}`, s),
    overrides: (s) => call(`${BASE}/overrides`, s),
    createOverride: (body) => send("POST", `${BASE}/overrides`, body, f ?? fetch),
    deleteOverride: (id) => send("DELETE", `${BASE}/overrides/${encodeURIComponent(String(id))}`, undefined, f ?? fetch),
    capabilities: (s) => call("/api/v1/auth/capabilities", s),
  };
}
