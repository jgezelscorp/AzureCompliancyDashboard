import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { MetricsApiProvider, USE_MOCK_DATA } from "./api/context";
import type { MetricsApi } from "./api/client";
import { completeSignInIfCallback, registerSessionTokenProvider } from "./auth/session";
import { ErrorState, Loading } from "./components/common";
import { CisoView } from "./pages/CisoView";
import { TechnicalView } from "./pages/TechnicalView";

/** Completes an Entra redirect before rendering; mock mode needs no sign-in. */
function AuthGate({ children, skip }: { children: ReactNode; skip: boolean }) {
  const [state, setState] = useState<"pending" | "ready" | Error>(skip ? "ready" : "pending");
  useEffect(() => {
    if (skip) return;
    registerSessionTokenProvider();
    completeSignInIfCallback().then(
      () => setState("ready"),
      (e: unknown) => setState(e instanceof Error ? e : new Error("Sign-in failed")),
    );
  }, [skip]);
  if (state === "pending") return <Loading what="sign-in" />;
  if (state instanceof Error) return <ErrorState error={state} />;
  return <>{children}</>;
}

export default function App({ api, skipAuth }: { api?: MetricsApi; skipAuth?: boolean }) {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header>
        <h1>Azure Compliancy Dashboard</h1>
        <nav aria-label="Primary">
          <NavLink to="/technical">Technical</NavLink> <NavLink to="/ciso">CISO</NavLink>
        </nav>
      </header>
      <main id="main" tabIndex={-1}>
        <AuthGate skip={skipAuth ?? (USE_MOCK_DATA || api !== undefined)}>
          <MetricsApiProvider api={api}>
            <Routes>
              <Route path="/" element={<Navigate to="/technical" replace />} />
              <Route path="/technical" element={<TechnicalView />} />
              <Route path="/ciso" element={<CisoView />} />
              <Route path="*" element={<p>Page not found.</p>} />
            </Routes>
          </MetricsApiProvider>
        </AuthGate>
      </main>
    </>
  );
}
