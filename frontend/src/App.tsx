import { useCallback, useEffect, useState, type ReactNode } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { MetricsApiProvider, USE_MOCK_DATA } from "./api/context";
import type { MetricsApi } from "./api/client";
import {
  completeSignInIfCallback,
  currentUserLogin,
  currentUserName,
  isSignedIn,
  registerSessionTokenProvider,
  signIn,
  signOut,
} from "./auth/session";
import { ErrorState, Loading } from "./components/common";
import { ThemeToggle } from "./components/ThemeToggle";
import { PolicyApiProvider } from "./api/policyContext";
import type { PolicyApi } from "./api/policyClient";
import { DomainApiProvider } from "./api/domainContext";
import type { DomainApi } from "./api/domainClient";
import { CisoView } from "./pages/CisoView";
import { PolicyOverviewPage } from "./pages/PolicyOverviewPage";
import { ExplorerPage } from "./pages/ExplorerPage";
import { ResourcePage } from "./pages/ResourcePage";
import { MachinePage } from "./pages/MachinePage";
import { TechnicalView } from "./pages/TechnicalView";

type AuthState =
  | { kind: "pending" }
  | { kind: "signedOut" }
  | { kind: "signedIn"; name: string | null; login: string | null }
  | { kind: "error"; error: Error };

function useAuth(skip: boolean) {
  const [state, setState] = useState<AuthState>(
    skip ? { kind: "signedIn", name: null, login: null } : { kind: "pending" },
  );
  useEffect(() => {
    if (skip) return;
    registerSessionTokenProvider();
    completeSignInIfCallback().then(
      () =>
        setState(
          isSignedIn()
            ? { kind: "signedIn", name: currentUserName(), login: currentUserLogin() }
            : { kind: "signedOut" },
        ),
      (e: unknown) =>
        setState({ kind: "error", error: e instanceof Error ? e : new Error("Sign-in failed") }),
    );
  }, [skip]);
  const run = useCallback((action: () => Promise<void>) => {
    action().catch((e: unknown) =>
      setState({ kind: "error", error: e instanceof Error ? e : new Error("Sign-in failed") }),
    );
  }, []);
  return {
    state,
    login: () => run(signIn),
    logout: () => run(signOut),
  };
}

function Landing({ onSignIn }: { onSignIn: () => void }) {
  return (
    <section className="landing" aria-labelledby="landing-h">
      <div className="landing-card">
        <p className="eyebrow">Azure Policy and Machine Configuration</p>
        <h2 id="landing-h">Sign in to view compliance posture</h2>
        <p className="detail">
          Sign in with your Microsoft Entra account. You only see subscriptions you can read under
          Azure RBAC; nothing is shown when access cannot be verified.
        </p>
        <button type="button" className="btn btn-primary btn-lg" onClick={onSignIn}>
          Sign in with Microsoft
        </button>
      </div>
    </section>
  );
}

export default function App({ api, policyApi, domainApi, skipAuth }: { api?: MetricsApi; policyApi?: PolicyApi; domainApi?: DomainApi; skipAuth?: boolean }) {
  const skip = skipAuth ?? (USE_MOCK_DATA || api !== undefined);
  const { state, login, logout } = useAuth(skip);
  const signedIn = state.kind === "signedIn";

  let body: ReactNode;
  if (state.kind === "pending") body = <Loading what="sign-in" />;
  else if (state.kind === "error") body = <ErrorState error={state.error} onRetry={login} />;
  else if (state.kind === "signedOut") body = <Landing onSignIn={login} />;
  else
    body = (
      <MetricsApiProvider api={api}>
       <PolicyApiProvider api={policyApi}>
        <DomainApiProvider api={domainApi}>
        <Routes>
          <Route path="/" element={<Navigate to="/overview" replace />} />
          <Route path="/overview" element={<PolicyOverviewPage />} />
          <Route path="/explorer" element={<ExplorerPage />} />
          <Route path="/resource" element={<ResourcePage />} />
          <Route path="/machine" element={<MachinePage />} />
          <Route path="/technical" element={<TechnicalView />} />
          <Route path="/ciso" element={<CisoView />} />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
        </DomainApiProvider>
       </PolicyApiProvider>
      </MetricsApiProvider>
    );

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="app-header">
        <div className="header-inner">
          <h1>
            <span className="logo" aria-hidden="true">
              ◆
            </span>
            Azure Compliancy Dashboard
          </h1>
          {signedIn && (
            <nav aria-label="Primary">
              <NavLink to="/overview">Overview</NavLink>
              <NavLink to="/explorer">Explorer</NavLink>
              <NavLink to="/technical">Technical</NavLink>
              <NavLink to="/ciso">CISO</NavLink>
            </nav>
          )}
          <div className="header-actions">
            <ThemeToggle />
            {!skip && state.kind === "signedIn" && (
              <>
                {state.name && (
                  <span className="user" title={state.login ? `${state.name} (${state.login})` : state.name}>
                    <span className="sr-only">Signed in as </span>
                    {state.name}
                    {state.login && <span className="user-login"> {state.login}</span>}
                  </span>
                )}
                <button type="button" className="btn" onClick={logout}>
                  Sign out
                </button>
              </>
            )}
            {!skip && state.kind === "signedOut" && (
              <button type="button" className="btn btn-primary" onClick={login}>
                Sign in
              </button>
            )}
          </div>
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        {body}
      </main>
    </>
  );
}
