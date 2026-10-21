/** Authorization code + PKCE helpers (RFC 7636). Pure functions; no storage or network. */

function base64Url(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function randomString(byteLength = 32): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64Url(bytes);
}

export async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64Url(new Uint8Array(digest));
}

export interface AuthorizeParams {
  authority: string;
  clientId: string;
  redirectUri: string;
  scope: string;
  state: string;
  challenge: string;
}

export function authorizeUrl(p: AuthorizeParams): string {
  const q = new URLSearchParams({
    client_id: p.clientId,
    response_type: "code",
    redirect_uri: p.redirectUri,
    response_mode: "query",
    scope: p.scope,
    state: p.state,
    code_challenge: p.challenge,
    code_challenge_method: "S256",
  });
  return `${p.authority}/oauth2/v2.0/authorize?${q.toString()}`;
}

export function tokenEndpoint(authority: string): string {
  return `${authority}/oauth2/v2.0/token`;
}

export function logoutUrl(authority: string, postLogoutRedirectUri: string): string {
  const q = new URLSearchParams({ post_logout_redirect_uri: postLogoutRedirectUri });
  return `${authority}/oauth2/v2.0/logout?${q.toString()}`;
}
