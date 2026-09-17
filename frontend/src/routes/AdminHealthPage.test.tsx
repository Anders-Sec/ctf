import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminHealthPage from "./AdminHealthPage";
import type { HealthCheck, HealthReport } from "../api/adminHealth";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function check(overrides: Partial<HealthCheck> = {}): HealthCheck {
  return { name: "Postgres", state: "ok", duration_ms: 6, detail: null, ...overrides };
}

function report(overrides: Partial<HealthReport> = {}): HealthReport {
  return {
    checked_at: "2026-09-17T14:31:02Z",
    checks: [check()],
    connections: { scoreboard: 47 },
    build: { version: "1.9.2", environment: "production" },
    load: {
      window_minutes: 15,
      requests_per_minute: 142,
      p95_ms: 180,
      errors: 0,
      uptime_seconds: 187200,
    },
    ...overrides,
  };
}

function render(data: HealthReport = report()) {
  stubFetch((path) => {
    if (path.endsWith("/auth/me")) {
      return { status: 200, body: me({ user: { ...me().user, role: "organizer" } }) };
    }
    if (path.endsWith("/admin/health")) {
      return { status: 200, body: data };
    }
    return { status: 200, body: {} };
  });
  renderApp(<AdminHealthPage />);
}

describe("AdminHealthPage", () => {
  it("names each check's state in words, not colour alone", async () => {
    render(report({ checks: [check({ name: "Redis", state: "down", detail: "TimeoutError" })] }));

    const row = (await screen.findByText("Redis")).closest("li")!;
    expect(within(row).getByText("down")).toBeInTheDocument();
    expect(within(row).getByText("TimeoutError")).toBeInTheDocument();
  });

  it("shows a deliberately-off feature as not configured, not as a fault", async () => {
    render(report({ checks: [check({ name: "Orchestrator", state: "not_configured" })] }));

    expect(await screen.findByText("not configured")).toBeInTheDocument();
  });

  it("links a failing dependency to the page you would go to next", async () => {
    render(report({ checks: [check({ name: "Mail relay", state: "down" })] }));

    const row = (await screen.findByText("Mail relay")).closest("li")!;
    expect(within(row).getByRole("link", { name: "Email Delivery" })).toHaveAttribute(
      "href",
      "/admin/email",
    );
  });

  it("reports the build and how long the process has been up", async () => {
    // Answers "did something restart?", which is the second question after
    // every unexplained weirdness.
    render();

    expect(await screen.findByText("1.9.2")).toBeInTheDocument();
    expect(screen.getByText("production")).toBeInTheDocument();
    // 187200s is 52 hours, which the formatter renders in days past the 48h mark.
    expect(screen.getByText("2d 4h")).toBeInTheDocument();
  });

  it("flags a non-zero error count", async () => {
    render(report({ load: { ...report().load, errors: 4 } }));

    expect(await screen.findByText("4")).toHaveClass("text-danger");
  });

  it("says plainly that the figures are per-process", async () => {
    // The honest limit, stated rather than hidden.
    render();

    expect(await screen.findByText(/reset when it restarts/i)).toBeInTheDocument();
  });

  it("shows live socket counts", async () => {
    render();

    expect(await screen.findByText("47")).toBeInTheDocument();
  });
});
