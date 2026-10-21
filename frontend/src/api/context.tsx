import { createContext, useContext, useMemo, type ReactNode } from "react";
import { createMetricsApi, type MetricsApi } from "./client";
import { createMockApi } from "./mock";

export const USE_MOCK_DATA = import.meta.env.VITE_USE_MOCK_DATA === "true";

const Ctx = createContext<MetricsApi | null>(null);

export function MetricsApiProvider({ api, children }: { api?: MetricsApi; children: ReactNode }) {
  const value = useMemo(() => api ?? (USE_MOCK_DATA ? createMockApi() : createMetricsApi()), [api]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useMetricsApi(): MetricsApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("MetricsApiProvider is missing");
  return v;
}
