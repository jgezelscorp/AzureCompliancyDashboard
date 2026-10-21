import type {
  AuthConfig,
  CategoryRow,
  CheckMachineRow,
  CheckRow,
  CollectionRun,
  HealthResponse,
  HistoryResponse,
  InfoResponse,
  LatestMetrics,
  MachinesResponse,
  MetricFamily,
  ScopesResponse,
} from "./types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "";

export type TokenProvider = () => Promise<string | null>;

let tokenProvider: TokenProvider = async () => null;

/** The sign-in layer registers how bearer tokens are obtained; tokens are never persisted here. */
export function setTokenProvider(provider: TokenProvider): void {
  tokenProvider = provider;
}

async function get<T>(
  path: string,
  fetchImpl: typeof fetch = fetch,
  options: { auth?: boolean; signal?: AbortSignal } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.auth) {
    const token = await tokenProvider();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  const res = await fetchImpl(`${BASE_URL}${path}`, { headers, signal: options.signal });
  if (!res.ok) {
    throw new ApiError(res.status, `GET ${path} failed with ${res.status}`);
  }
  return (await res.json()) as T;
}

function query(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export interface MetricsApi {
  latest(signal?: AbortSignal): Promise<LatestMetrics>;
  scopes(signal?: AbortSignal): Promise<ScopesResponse>;
  history(family: MetricFamily, signal?: AbortSignal): Promise<HistoryResponse>;
  machines(family: MetricFamily, signal?: AbortSignal): Promise<MachinesResponse>;
  categories(
    family: MetricFamily,
    subscriptionId?: string,
    signal?: AbortSignal,
  ): Promise<{ snapshotAt: string | null; categories: CategoryRow[] }>;
  checks(
    family: MetricFamily,
    category: string,
    subscriptionId?: string,
    signal?: AbortSignal,
  ): Promise<{ snapshotAt: string | null; checks: CheckRow[] }>;
  checkMachines(
    family: MetricFamily,
    checkKey: string,
    subscriptionId?: string,
    signal?: AbortSignal,
  ): Promise<{ snapshotAt: string | null; machines: CheckMachineRow[] }>;
  runs(signal?: AbortSignal): Promise<{ runs: CollectionRun[] }>;
}

export function createMetricsApi(f?: typeof fetch): MetricsApi {
  const call = <T>(path: string, signal?: AbortSignal) => get<T>(path, f, { auth: true, signal });
  return {
    latest: (s) => call("/api/v1/metrics/latest", s),
    scopes: (s) => call("/api/v1/metrics/scopes", s),
    history: (family, s) => call(`/api/v1/metrics/history${query({ family })}`, s),
    machines: (family, s) => call(`/api/v1/metrics/machines${query({ family, limit: 500 })}`, s),
    categories: (family, subscriptionId, s) =>
      call(`/api/v1/metrics/categories${query({ family, subscriptionId })}`, s),
    checks: (family, category, subscriptionId, s) =>
      call(`/api/v1/metrics/checks${query({ family, category, subscriptionId })}`, s),
    checkMachines: (family, checkKey, subscriptionId, s) =>
      call(`/api/v1/metrics/checks/machines${query({ family, checkKey, subscriptionId })}`, s),
    runs: (s) => call("/api/v1/collection/runs", s),
  };
}

export const api = {
  health: (f?: typeof fetch) => get<HealthResponse>("/healthz", f),
  info: (f?: typeof fetch) => get<InfoResponse>("/api/v1/info", f),
  authConfig: (f?: typeof fetch) => get<AuthConfig>("/api/v1/auth/config", f),
};
