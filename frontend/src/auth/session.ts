import { api, setTokenProvider } from "../api/client";
import { authorizeUrl, challengeFor, logoutUrl, randomString, tokenEndpoint } from "./pkce";

const PENDING_KEY = "acd.pkce";
const EXPIRY_MARGIN_MS = 60_000;

interface Token {
  value: string;
  expiresAt: number;
}

/** Access tokens live in memory only; only the short-lived PKCE verifier/state use sessionStorage. */
let token: Token | null = null;
let userName: string | null = null;

export function isSignedIn(now = Date.now()): boolean {
  return token !== null && token.expiresAt - EXPIRY_MARGIN_MS > now;
}

export async function signIn(): Promise<void> {
  const cfg = await api.authConfig();
  const verifier = randomString(48);
  const state = randomString(16);
  sessionStorage.setItem(PENDING_KEY, JSON.stringify({ verifier, state }));
  window.location.assign(
    authorizeUrl({
      authority: cfg.authority,
      clientId: cfg.spaClientId,
      redirectUri: window.location.origin,
      scope: cfg.apiScope,
      state,
      challenge: await challengeFor(verifier),
    }),
  );
}

/** Completes the redirect, returns true when this page load was an auth callback. */
export async function completeSignInIfCallback(): Promise<boolean> {
  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");
  const state = params.get("state");
  if (!code || !state) return false;
  const pending = sessionStorage.getItem(PENDING_KEY);
  sessionStorage.removeItem(PENDING_KEY);
  window.history.replaceState({}, "", window.location.pathname);
  if (!pending) throw new Error("Sign-in response without a pending request");
  const { verifier, state: expected } = JSON.parse(pending) as { verifier: string; state: string };
  if (state !== expected) throw new Error("Sign-in state mismatch");
  const cfg = await api.authConfig();
  const res = await fetch(tokenEndpoint(cfg.authority), {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: cfg.spaClientId,
      grant_type: "authorization_code",
      code,
      redirect_uri: window.location.origin,
      code_verifier: verifier,
      scope: cfg.apiScope,
    }),
  });
  if (!res.ok) throw new Error(`Token request failed with ${res.status}`);
  const body = (await res.json()) as { access_token: string; expires_in: number };
  token = { value: body.access_token, expiresAt: Date.now() + body.expires_in * 1000 };
  userName = nameFromToken(body.access_token);
  return true;
}

export function registerSessionTokenProvider(): void {
  setTokenProvider(async () => {
    if (!isSignedIn()) {
      await signIn();
      return new Promise<never>(() => undefined); // navigating away
    }
    return token?.value ?? null;
  });
}

export function signOutLocal(): void {
  token = null;
  userName = null;
}

/** Display name from the token claims; the token is only decoded for display, never trusted. */
export function currentUserName(): string | null {
  return isSignedIn() ? userName : null;
}

function nameFromToken(jwt: string): string | null {
  try {
    const payload = jwt.split(".")[1]?.replace(/-/g, "+").replace(/_/g, "/");
    if (!payload) return null;
    const claims = JSON.parse(atob(payload)) as Record<string, unknown>;
    for (const key of ["name", "preferred_username", "upn", "email"]) {
      const v = claims[key];
      if (typeof v === "string" && v) return v;
    }
  } catch {
    // opaque or malformed token: no display name
  }
  return null;
}

/** Clears the session and the sessionStorage state, then ends the Entra session. */
export async function signOut(): Promise<void> {
  signOutLocal();
  sessionStorage.removeItem(PENDING_KEY);
  const cfg = await api.authConfig();
  window.location.assign(logoutUrl(cfg.authority, window.location.origin));
}
