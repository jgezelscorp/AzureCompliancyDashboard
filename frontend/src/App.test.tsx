import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ApiError, api } from "./api/client";
import App from "./App";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("routing", () => {
  it("redirects root to the technical view", () => {
    renderAt("/");
    expect(screen.getByRole("heading", { name: "Technical view" })).toBeInTheDocument();
  });

  it("renders the CISO view", () => {
    renderAt("/ciso");
    expect(screen.getByRole("heading", { name: "CISO view" })).toBeInTheDocument();
  });
});

describe("api client", () => {
  it("returns typed JSON", async () => {
    const f = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok", version: "1" })));
    const res = await api.health(f as unknown as typeof fetch);
    expect(res.status).toBe("ok");
  });

  it("throws ApiError on failure", async () => {
    const f = vi.fn().mockResolvedValue(new Response("nope", { status: 500 }));
    await expect(api.info(f as unknown as typeof fetch)).rejects.toBeInstanceOf(ApiError);
  });
});
