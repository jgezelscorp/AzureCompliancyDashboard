import { get } from "./client";
import type {
  Breakdown,
  Exemptions,
  FilterOptions,
  Filters,
  MachineCoverage,
  MachineDetail,
  PolicyOverview,
  Quality,
  ResourceDetail,
  ResourceRow,
  Page,
  StatesPage,
  TopPolicy,
  Trend,
} from "./policyTypes";

const BASE = "/api/v1/policy";

/** Serializes filters and paging as repeated query parameters (never JSON in the URL). */
export function policyQuery(
  filters: Filters = {},
  extra: Record<string, string | number | boolean | undefined> = {},
): string {
  const q = new URLSearchParams();
  for (const [k, values] of Object.entries(filters)) {
    for (const v of values ?? []) if (v !== "") q.append(k, v);
  }
  for (const [k, v] of Object.entries(extra)) {
    if (v !== undefined && v !== "") q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export interface PageOptions {
  limit?: number;
  offset?: number;
  sort?: string;
  desc?: boolean;
}

export interface PolicyApi {
  overview(filters: Filters, signal?: AbortSignal): Promise<PolicyOverview>;
  breakdown(
    dim: string,
    filters: Filters,
    page?: PageOptions,
    signal?: AbortSignal,
  ): Promise<Breakdown>;
  topPolicies(filters: Filters, limit?: number, signal?: AbortSignal): Promise<{ rows: TopPolicy[]; grain: string }>;
  states(filters: Filters, page: PageOptions, signal?: AbortSignal): Promise<StatesPage>;
  resources(filters: Filters, page: PageOptions, signal?: AbortSignal): Promise<Page<ResourceRow>>;
  resource(id: string, signal?: AbortSignal): Promise<ResourceDetail>;
  exemptions(status: string, signal?: AbortSignal): Promise<Exemptions>;
  trend(signal?: AbortSignal): Promise<Trend>;
  filters(signal?: AbortSignal): Promise<FilterOptions>;
  quality(signal?: AbortSignal): Promise<Quality>;
  machineCoverage(signal?: AbortSignal): Promise<MachineCoverage>;
  machineDetail(id: string, signal?: AbortSignal): Promise<MachineDetail>;
}

export function createPolicyApi(f?: typeof fetch): PolicyApi {
  const call = <T>(path: string, signal?: AbortSignal) => get<T>(path, f, { auth: true, signal });
  const paging = (p: PageOptions = {}) => ({
    limit: p.limit,
    offset: p.offset,
    sort: p.sort,
    desc: p.desc === undefined ? undefined : p.desc,
  });
  return {
    overview: (flt, s) => call(`${BASE}/overview${policyQuery(flt)}`, s),
    breakdown: (dim, flt, page, s) =>
      call(`${BASE}/breakdown${policyQuery(flt, { dim, ...paging(page) })}`, s),
    topPolicies: (flt, limit, s) => call(`${BASE}/top-policies${policyQuery(flt, { limit })}`, s),
    states: (flt, page, s) => call(`${BASE}/states${policyQuery(flt, paging(page))}`, s),
    resources: (flt, page, s) => call(`${BASE}/resources${policyQuery(flt, paging(page))}`, s),
    resource: (id, s) => call(`${BASE}/resource${policyQuery({}, { id })}`, s),
    exemptions: (status, s) => call(`${BASE}/exemptions${policyQuery({}, { status })}`, s),
    trend: (s) => call(`${BASE}/trend`, s),
    filters: (s) => call(`${BASE}/filters`, s),
    quality: (s) => call(`${BASE}/quality`, s),
    machineCoverage: (s) => call(`${BASE}/machines/coverage`, s),
    machineDetail: (id, s) => call(`${BASE}/machines/detail${policyQuery({}, { id })}`, s),
  };
}
