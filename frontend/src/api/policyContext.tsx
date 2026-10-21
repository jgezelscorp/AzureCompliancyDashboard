import { createContext, useContext, useMemo, type ReactNode } from "react";
import { USE_MOCK_DATA } from "./context";
import { createPolicyApi, type PolicyApi } from "./policyClient";
import { createMockPolicyApi } from "./policyMock";

const Ctx = createContext<PolicyApi | null>(null);

export function PolicyApiProvider({ api, children }: { api?: PolicyApi; children: ReactNode }) {
  const value = useMemo(() => api ?? (USE_MOCK_DATA ? createMockPolicyApi() : createPolicyApi()), [api]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePolicyApi(): PolicyApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("PolicyApiProvider is missing");
  return v;
}
