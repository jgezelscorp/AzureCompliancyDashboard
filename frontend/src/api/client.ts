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
  ExportJob,
  ExportRequest,
} from "./types";

export class ApiError extends Error {
  constructor(
    /** HTTP status; 0 = network failure (no response), -1 = response body incomplete/unreadable. */
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function isAbort(e: unknown): boolean {
  return e instanceof DOMException && e.name === "AbortError";
}

async function request(fetchImpl: typeof fetch, url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetchImpl(url, init);
  } catch (e) {
    if (isAbort(e)) throw e;
    throw new ApiError(0, `${init.method ?? "GET"} ${url} could not reach the service`);
  }
}

async function readJson<T>(res: Response, what: string): Promise<T> {
  try {
    return (await res.json()) as T;
  } catch (e) {
    if (isAbort(e)) throw e;
    throw new ApiError(-1, `${what} returned an incomplete or unreadable body`);
  }
}

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "";

export type TokenProvider = () => Promise<string | null>;

let tokenProvider: TokenProvider = async () => null;

/** The sign-in layer registers how bearer tokens are obtained; tokens are never persisted here. */
export function setTokenProvider(provider: TokenProvider): void {
  tokenProvider = provider;
}

export async function get<T>(
  path: string,
  fetchImpl: typeof fetch = fetch,
  options: { auth?: boolean; signal?: AbortSignal } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.auth) {
    const token = await tokenProvider();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  const res = await request(fetchImpl, `${BASE_URL}${path}`, { headers, signal: options.signal });
  if (!res.ok) {
    throw new ApiError(res.status, `GET ${path} failed with ${res.status}`);
  }
  return readJson<T>(res, `GET ${path}`);
}

export async function send<T>(
  method: "POST" | "GET" | "DELETE",
  path: string,
  body: unknown,
  fetchImpl: typeof fetch,
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = await tokenProvider();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await request(fetchImpl, `${BASE_URL}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(res.status, `${method} ${path} failed with ${res.status}`);
  if (res.status === 204) return undefined as T;
  return readJson<T>(res, `${method} ${path}`);
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
  ): Promise<{ snapshotAt: string | null; category?: string; checks: CheckRow[] }>;
  checkMachines(
    family: MetricFamily,
    checkKey: string,
    subscriptionId?: string,
    signal?: AbortSignal,
  ): Promise<{ snapshotAt: string | null; machines: CheckMachineRow[] }>;
  runs(signal?: AbortSignal): Promise<{ runs: CollectionRun[] }>;
  createExport(request: ExportRequest): Promise<ExportJob>;
  listExports(signal?: AbortSignal): Promise<{ jobs: ExportJob[] }>;
  /** Authenticated, re-authorized download; there is no shareable link. */
  downloadExport(jobId: string): Promise<{ blob: Blob; filename: string }>;
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
    createExport: (request) => send<ExportJob>("POST", "/api/v1/exports", request, f ?? fetch),
    listExports: (s) => call("/api/v1/exports", s),
    downloadExport: async (jobId) => {
      const headers: Record<string, string> = {};
      const token = await tokenProvider();
      if (token) headers.Authorization = `Bearer ${token}`;
      const path = `/api/v1/exports/${encodeURIComponent(jobId)}/download`;
      const res = await request(f ?? fetch, `${BASE_URL}${path}`, { headers });
      if (!res.ok) throw new ApiError(res.status, `GET ${path} failed with ${res.status}`);
      const match = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "");
      return { blob: await res.blob(), filename: match?.[1] ?? "export" };
    },
  };
}

export const api = {
  health: (f?: typeof fetch) => get<HealthResponse>("/healthz", f),
  info: (f?: typeof fetch) => get<InfoResponse>("/api/v1/info", f),
  authConfig: (f?: typeof fetch) => get<AuthConfig>("/api/v1/auth/config", f),
};
