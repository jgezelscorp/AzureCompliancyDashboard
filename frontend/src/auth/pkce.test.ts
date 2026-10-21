import { describe, expect, it } from "vitest";
import { authorizeUrl, challengeFor, randomString, tokenEndpoint } from "./pkce";

describe("PKCE helpers (RFC 7636)", () => {
  it("derives the S256 challenge from the RFC 7636 appendix B vector", async () => {
    const verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
    expect(await challengeFor(verifier)).toBe("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
  });

  it("generates URL-safe, high-entropy, non-repeating verifiers within RFC length limits", () => {
    const seen = new Set<string>();
    for (let i = 0; i < 50; i++) {
      const v = randomString(48);
      expect(v).toMatch(/^[A-Za-z0-9_-]+$/);
      expect(v.length).toBeGreaterThanOrEqual(43);
      expect(v.length).toBeLessThanOrEqual(128);
      seen.add(v);
    }
    expect(seen.size).toBe(50);
  });

  it("builds an authorization-code request that only uses S256 and never carries the verifier", () => {
    const url = new URL(
      authorizeUrl({
        authority: "https://login.example.invalid/00000000-0000-0000-0000-000000000000",
        clientId: "client",
        redirectUri: "https://app.example.invalid",
        scope: "api://client/access",
        state: "st",
        challenge: "ch",
      }),
    );
    expect(url.pathname.endsWith("/oauth2/v2.0/authorize")).toBe(true);
    const q = url.searchParams;
    expect(q.get("response_type")).toBe("code");
    expect(q.get("code_challenge_method")).toBe("S256");
    expect(q.get("code_challenge")).toBe("ch");
    expect(q.get("state")).toBe("st");
    expect(q.has("code_verifier")).toBe(false);
    expect(q.has("client_secret")).toBe(false);
  });

  it("targets the v2 token endpoint of the authority", () => {
    expect(tokenEndpoint("https://login.example.invalid/t")).toBe(
      "https://login.example.invalid/t/oauth2/v2.0/token",
    );
  });
});
