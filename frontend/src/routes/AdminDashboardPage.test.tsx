import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminDashboardPage from "./AdminDashboardPage";
import type { ChallengeHealth, Dashboard } from "../api/adminOps";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function dashboard(overrides: Partial<Dashboard["attention"]> = {}): Dashboard {
  return {
    generated_at: "2026-09-06T12:00:00Z",
    event: {
      name: "Autumn Crawl",
      starts_at: "2026-09-06T09:00:00Z",
      ends_at: "2026-09-08T17:00:00Z",
      running: true,
      server_time: "2026-09-06T12:00:00Z",
    },
    pulse: {
      solves_5m: 3,
      solves_15m: 11,
      solves_60m: 42,
      submissions_15m: 90,
      active_players_15m: 27,
    },
    attention: {
      open_reports: 0,
      pending_approvals: 0,
      drafts_after_start: 0,
      published_without_answers: [],
      suspected_broken: [],
      ...overrides,
    },
    containers: { available: false, note: "Instances arrive with spec 009." },
  };
}

function health(overrides: Partial<ChallengeHealth> = {}): ChallengeHealth {
  return {
    challenge_id: "c1",
    title: "Packet Puzzle",
    state: "published",
    solve_count: 4,
    attempt_count: 20,
    open_reports: 0,
    suspected_broken: false,
    suspiciously_easy: false,
    ...overrides,
  };
}

function render(board: Dashboard, rows: ChallengeHealth[] = []) {
  stubFetch((path) => {
    if (path.endsWith("/auth/me")) return { status: 200, body: me() };
    if (path.includes("challenge-health")) return { status: 200, body: rows };
    return { status: 200, body: board };
  });
  renderApp(<AdminDashboardPage />);
}

describe("AdminDashboardPage", () => {
  it("shows the event pulse", async () => {
    render(dashboard());

    expect(await screen.findByText("Solves · 15 min")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("says plainly when nothing needs attention", async () => {
    render(dashboard());

    expect(await screen.findByText(/nothing is on fire/i)).toBeInTheDocument();
  });

  it("shouts about a challenge nobody can solve", async () => {
    // The single most valuable thing this screen can tell an organiser.
    render(
      dashboard({
        suspected_broken: [{ challenge_id: "c9", title: "Impossible", attempts: 80 }],
      }),
    );

    const alert = await screen.findByText(/80 attempts, nobody has solved it/i);
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toContain("Impossible");
  });

  it("shouts about a published challenge with no answer rules", async () => {
    render(
      dashboard({
        published_without_answers: [{ challenge_id: "c8", title: "Answerless" }],
      }),
    );

    expect(await screen.findByText(/cannot be\s+solved/i)).toBeInTheDocument();
  });

  it("links open reports to the triage screen", async () => {
    render(dashboard({ open_reports: 3 }));

    expect(await screen.findByText(/3 open reports/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /triage/i })).toHaveAttribute("href", "/admin/ops");
  });

  it("links pending approvals to the approval queue", async () => {
    render(dashboard({ pending_approvals: 5 }));

    expect(await screen.findByRole("link", { name: /review/i })).toHaveAttribute(
      "href",
      "/admin/users",
    );
  });

  it("marks an untouched challenge as untouched rather than as a failure", async () => {
    render(dashboard(), [health({ attempt_count: 0, solve_count: 0 })]);

    expect(await screen.findByText("untouched")).toBeInTheDocument();
  });

  it("flags a likely-broken challenge in the health table", async () => {
    render(dashboard(), [health({ suspected_broken: true, solve_count: 0 })]);

    expect(await screen.findByText(/likely broken/i)).toBeInTheDocument();
  });

  it("is honest that the container panel is empty", async () => {
    render(dashboard());

    expect(await screen.findByText(/instances arrive with spec 009/i)).toBeInTheDocument();
  });
});
