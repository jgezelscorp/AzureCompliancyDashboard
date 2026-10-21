import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "./App";
import { ApiError, type MetricsApi } from "./api/client";
import { createMockApi } from "./api/mock";

function renderAt(path: string, api: MetricsApi) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App api={api} />
    </MemoryRouter>,
  );
}

function failing(status: number): MetricsApi {
  const reject = () => Promise.reject(new ApiError(status, "boom"));
  return { ...createMockApi(), latest: reject, scopes: reject, history: reject };
}

describe("App", () => {
  it("shows navigation and the Technical view by default", async () => {
    renderAt("/", createMockApi());
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Azure Compliancy Dashboard");
    expect(screen.getByRole("link", { name: "CISO" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /technical/i })).toBeInTheDocument();
  });

  it("renders the CISO view with honesty labels", async () => {
    renderAt("/ciso", createMockApi());
    expect(await screen.findByRole("heading", { name: "CISO view" })).toBeInTheDocument();
    expect((await screen.findAllByText(/certif/i)).length).toBeGreaterThan(0);
  });

  it("never labels missing data as meeting target", async () => {
    renderAt("/ciso", createMockApi());
    await screen.findByRole("heading", { name: "CISO view" });
    await waitFor(() => expect(screen.getAllByText(/Coverage gaps/i).length).toBeGreaterThan(0));
  });

  it("explains 403 without leaking data", async () => {
    renderAt("/ciso", failing(403));
    expect(await screen.findByRole("alert")).toHaveTextContent(/access denied/i);
  });

  it("offers retry on server errors", async () => {
    renderAt("/ciso", failing(500));
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
