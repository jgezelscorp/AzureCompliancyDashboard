import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { ApiError, createMetricsApi, setTokenProvider, type MetricsApi } from "./api/client";
import { createMockApi } from "./api/mock";

function renderAt(path: string, api: MetricsApi) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App api={api} />
    </MemoryRouter>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("export controls", () => {
  it("offers CSV and PDF exports in the Technical view and lists the created job", async () => {
    const api = createMockApi();
    const create = vi.spyOn(api, "createExport");
    renderAt("/technical", api);
    fireEvent.click(await screen.findByRole("button", { name: "Export checks CSV" }));
    await screen.findByRole("button", { name: "Download" });
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ format: "csv", dataset: "checks", family: "AzureWindowsBaseline" }),
    );
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export technical PDF" })).toBeInTheDocument();
  });

  it("passes the selected scope filter to the export", async () => {
    const api = createMockApi();
    const create = vi.spyOn(api, "createExport");
    renderAt("/technical?scope=00000000-0000-0000-0000-000000000001", api);
    fireEvent.click(await screen.findByRole("button", { name: "Export machines CSV" }));
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0][0].subscriptionId).toBe("00000000-0000-0000-0000-000000000001");
  });

  it("offers the executive PDF in the CISO view with the disclosure text", async () => {
    renderAt("/ciso", createMockApi());
    expect(await screen.findByRole("button", { name: "Export executive PDF" })).toBeInTheDocument();
    expect(screen.getByText(/not a certification/i)).toBeInTheDocument();
  });

  it("downloads through the authenticated API and revokes the object URL", async () => {
    const api = createMockApi();
    URL.createObjectURL = vi.fn(() => "blob:synthetic");
    URL.revokeObjectURL = vi.fn();
    const dl = vi.spyOn(api, "downloadExport");
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderAt("/technical", api);
    fireEvent.click(await screen.findByRole("button", { name: "Export checks CSV" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download" }));
    await waitFor(() => expect(dl).toHaveBeenCalled());
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:synthetic"));
  });

  it("explains a denied or expired download without exposing data", async () => {
    const api = createMockApi();
    api.downloadExport = () => Promise.reject(new ApiError(403, "no"));
    renderAt("/technical", api);
    fireEvent.click(await screen.findByRole("button", { name: "Export checks CSV" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download" }));
    expect(await screen.findByText(/re-verified or has changed/i)).toBeInTheDocument();
    api.downloadExport = () => Promise.reject(new ApiError(410, "gone"));
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(await screen.findByText(/has expired/i)).toBeInTheDocument();
  });

  it("shows a failure when creating an export is denied", async () => {
    const api = createMockApi();
    api.createExport = () => Promise.reject(new ApiError(403, "no"));
    renderAt("/technical", api);
    fireEvent.click(await screen.findByRole("button", { name: "Export checks CSV" }));
    expect(await screen.findByText(/Export denied/i)).toBeInTheDocument();
  });
});

describe("export api client", () => {
  it("posts with a bearer token and downloads with the file name from the server", async () => {
    setTokenProvider(async () => "test-token");
    const f = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ jobId: "j1" }), { status: 201 }))
      .mockResolvedValueOnce(
        new Response("a,b", {
          status: 200,
          headers: { "Content-Disposition": 'attachment; filename="x.csv"' },
        }),
      );
    const api = createMetricsApi(f as unknown as typeof fetch);
    await api.createExport({ format: "csv", family: "AzureWindowsBaseline" });
    const [url, init] = f.mock.calls[0];
    expect(String(url)).toContain("/api/v1/exports");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-token");
    const out = await api.downloadExport("j1");
    expect(out.filename).toBe("x.csv");
    expect(new Headers(f.mock.calls[1][1].headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("surfaces download errors as ApiError", async () => {
    setTokenProvider(async () => null);
    const f = vi.fn().mockResolvedValue(new Response("", { status: 410 }));
    const api = createMetricsApi(f as unknown as typeof fetch);
    await expect(api.downloadExport("j1")).rejects.toMatchObject({ status: 410 });
  });
});
