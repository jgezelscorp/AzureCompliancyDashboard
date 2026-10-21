import type { HealthResponse, InfoResponse } from "./types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "";

async function get<T>(path: string, fetchImpl: typeof fetch = fetch): Promise<T> {
  const res = await fetchImpl(`${BASE_URL}${path}`, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    throw new ApiError(res.status, `GET ${path} failed with ${res.status}`);
  }
  return (await res.json()) as T;
}

export const api = {
  health: (f?: typeof fetch) => get<HealthResponse>("/healthz", f),
  info: (f?: typeof fetch) => get<InfoResponse>("/api/v1/info", f),
};
