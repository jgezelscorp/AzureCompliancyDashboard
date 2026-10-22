import { createContext, useContext, useMemo, type ReactNode } from "react";
import { USE_MOCK_DATA } from "./context";
import { createDomainApi, type DomainApi } from "./domainClient";
import { createMockDomainApi } from "./domainMock";

const Ctx = createContext<DomainApi | null>(null);

export function DomainApiProvider({ api, children }: { api?: DomainApi; children: ReactNode }) {
  const value = useMemo(() => api ?? (USE_MOCK_DATA ? createMockDomainApi() : createDomainApi()), [api]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useDomainApi(): DomainApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("DomainApiProvider is missing");
  return v;
}
