import { describe, expect, it, vi } from "vitest";
import { ApiError, createMetricsApi, setTokenProvider } from "./client";

function fakeFetch(status: number, body: unknown) {
  return vi.fn(async (...args: [RequestInfo | URL, RequestInit?]) => {
    void args;
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
}

describe("metrics api client", () => {
  it("sends a bearer token and query parameters", async () => {
    setTokenProvider(async () => "test-token");
    const f = fakeFetch(200, { family: "AzureWindowsBaseline", points: [] });
    const api = createMetricsApi(f as unknown as typeof fetch);
    await api.categories("AzureWindowsBaseline", "sub-1");
    const [url, init] = f.mock.calls[0];
    expect(String(url)).toContain("/api/v1/metrics/categories");
    expect(String(url)).toContain("family=AzureWindowsBaseline");
    expect(String(url)).toContain("subscriptionId=sub-1");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("throws ApiError carrying the status", async () => {
    setTokenProvider(async () => null);
    const api = createMetricsApi(fakeFetch(403, {}) as unknown as typeof fetch);
    await expect(api.latest()).rejects.toMatchObject({ status: 403 });
    await expect(api.latest()).rejects.toBeInstanceOf(ApiError);
  });

  it("classifies network failures (status 0) and truncated bodies (status -1)", async () => {
    setTokenProvider(async () => null);
    const down = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(createMetricsApi(down as unknown as typeof fetch).latest()).rejects.toMatchObject({
      status: 0,
    });
    const cut = vi.fn(async () => new Response('{"checks": [', { status: 200 }));
    await expect(createMetricsApi(cut as unknown as typeof fetch).latest()).rejects.toMatchObject({
      status: -1,
    });
  });
});
