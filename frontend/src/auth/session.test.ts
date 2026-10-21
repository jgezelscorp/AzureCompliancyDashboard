import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  api: {
    authConfig: vi.fn(async () => ({
      authority: "https://login.example.invalid/00000000-0000-0000-0000-000000000000",
      spaClientId: "spa-client",
      apiScope: "api://api-client/access",
    })),
  },
  setTokenProvider: vi.fn(),
}));

import { completeSignInIfCallback, isSignedIn, signIn, signOutLocal } from "./session";

const originalLocation = window.location;

function setLocation(search: string, assign = vi.fn()) {
  Object.defineProperty(window, "location", {
    configurable: true,
    value: {
      origin: "https://app.example.invalid",
      pathname: "/",
      search,
      assign,
    },
  });
  return assign;
}

describe("PKCE sign-in session", () => {
  beforeEach(() => {
    sessionStorage.clear();
    signOutLocal();
    vi.spyOn(window.history, "replaceState").mockImplementation(() => undefined);
  });
  afterEach(() => {
    Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
    vi.restoreAllMocks();
  });

  it("redirects with an S256 challenge and keeps verifier and state only in sessionStorage", async () => {
    const assign = setLocation("");
    await signIn();
    const target = new URL(assign.mock.calls[0][0] as string);
    const pending = JSON.parse(sessionStorage.getItem("acd.pkce")!) as {
      verifier: string;
      state: string;
    };
    expect(target.searchParams.get("code_challenge_method")).toBe("S256");
    expect(target.searchParams.get("state")).toBe(pending.state);
    expect(target.searchParams.get("code_challenge")).not.toBe(pending.verifier);
    expect(target.toString()).not.toContain(pending.verifier);
    expect(localStorage.length).toBe(0);
  });

  it("ignores page loads that are not an auth callback", async () => {
    setLocation("?foo=bar");
    expect(await completeSignInIfCallback()).toBe(false);
  });

  it("rejects a callback with no pending request or a mismatched state, without calling the token endpoint", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    setLocation("?code=abc&state=zzz");
    await expect(completeSignInIfCallback()).rejects.toThrow(/pending/i);
    sessionStorage.setItem("acd.pkce", JSON.stringify({ verifier: "v", state: "expected" }));
    setLocation("?code=abc&state=zzz");
    await expect(completeSignInIfCallback()).rejects.toThrow(/state mismatch/i);
    expect(sessionStorage.getItem("acd.pkce")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(isSignedIn()).toBe(false);
    vi.unstubAllGlobals();
  });

  it("exchanges the code with the verifier and holds the token in memory only", async () => {
    const fetchMock = vi.fn(async () =>
      Response.json({ access_token: "synthetic-access-token", expires_in: 3600 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    sessionStorage.setItem("acd.pkce", JSON.stringify({ verifier: "the-verifier", state: "s1" }));
    setLocation("?code=the-code&state=s1");
    expect(await completeSignInIfCallback()).toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/oauth2\/v2\.0\/token$/);
    const body = new URLSearchParams(init.body as URLSearchParams);
    expect(body.get("grant_type")).toBe("authorization_code");
    expect(body.get("code")).toBe("the-code");
    expect(body.get("code_verifier")).toBe("the-verifier");
    expect(body.has("client_secret")).toBe(false);
    expect(isSignedIn()).toBe(true);
    expect(JSON.stringify({ ...sessionStorage })).not.toContain("synthetic-access-token");
    expect(JSON.stringify({ ...localStorage })).not.toContain("synthetic-access-token");
    expect(sessionStorage.getItem("acd.pkce")).toBeNull();
    signOutLocal();
    expect(isSignedIn()).toBe(false);
    vi.unstubAllGlobals();
  });

  it("fails when the token endpoint rejects the code and stays signed out", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("no", { status: 400 })));
    sessionStorage.setItem("acd.pkce", JSON.stringify({ verifier: "v", state: "s1" }));
    setLocation("?code=c&state=s1");
    await expect(completeSignInIfCallback()).rejects.toThrow(/400/);
    expect(isSignedIn()).toBe(false);
    vi.unstubAllGlobals();
  });

  it("treats a token that is about to expire as signed out", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ access_token: "t", expires_in: 30 })));
    sessionStorage.setItem("acd.pkce", JSON.stringify({ verifier: "v", state: "s1" }));
    setLocation("?code=c&state=s1");
    await completeSignInIfCallback();
    expect(isSignedIn()).toBe(false);
    vi.unstubAllGlobals();
  });
});
