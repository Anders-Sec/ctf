import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminScoreboardPage from "./AdminScoreboardPage";
import type { AdminBoard, AdminPlayerRow, UnrankedRow } from "../api/adminScoreboard";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function player(overrides: Partial<AdminPlayerRow> = {}): AdminPlayerRow {
  return {
    rank: 1,
    user_id: "11111111-0000-0000-0000-000000000001",
    display_name: "Rin",
    team_id: null,
    team_name: "The Bold",
    score: 125,
    level: 3,
    solve_count: 4,
    last_gain_at: "2026-09-17T11:00:00Z",
    solve_points: 100,
    adjustment_points: 25,
    ...overrides,
  };
}

function board(overrides: Partial<AdminBoard> = {}): AdminBoard {
  return {
    generated_at: "2026-09-17T12:00:00Z",
    server_time: "2026-09-17T12:00:00Z",
    players: [player()],
    teams: [],
    unranked: [],
    ...overrides,
  };
}

function render(data: AdminBoard = board()) {
  stubFetch((path) => {
    if (path.endsWith("/auth/me")) {
      return { status: 200, body: me({ user: { ...me().user, role: "organizer" } }) };
    }
    if (path.endsWith("/admin/scoreboard")) {
      return { status: 200, body: data };
    }
    return { status: 200, body: {} };
  });
  renderApp(<AdminScoreboardPage />);
}

describe("AdminScoreboardPage", () => {
  it("breaks the total into solve points and adjustments", async () => {
    // The answer when someone asks why a score looks wrong — and deliberately
    // invisible on the public board.
    render();
    const row = (await screen.findByText("Rin")).closest("tr")!;

    expect(within(row).getByText("100")).toBeInTheDocument();
    expect(within(row).getByText("+25")).toBeInTheDocument();
    expect(within(row).getByText("125")).toBeInTheDocument();
  });

  it("shows a dash rather than a zero when nothing was adjusted", async () => {
    render(board({ players: [player({ adjustment_points: 0, score: 100 })] }));
    const row = (await screen.findByText("Rin")).closest("tr")!;

    expect(within(row).getByText("—")).toBeInTheDocument();
  });

  it("marks a negative adjustment differently from a positive one", async () => {
    render(board({ players: [player({ adjustment_points: -10, score: 90 })] }));
    const row = (await screen.findByText("Rin")).closest("tr")!;

    expect(within(row).getByText("-10")).toHaveClass("text-danger");
  });

  it("shows the tie-break timestamp rather than asking you to trust the sort", async () => {
    render();
    const row = (await screen.findByText("Rin")).closest("tr")!;

    expect(within(row).getByText(/2026|11:00|:00/)).toBeInTheDocument();
  });

  it("lists accounts kept off the public board, with the reason", async () => {
    const ghost: UnrankedRow = {
      user_id: "22222222-0000-0000-0000-000000000002",
      display_name: "Ghost",
      solve_points: 80,
      adjustment_points: 0,
      score: 80,
      status: "disabled",
      role: "player",
      reason: "disabled",
    };
    render(board({ unranked: [ghost] }));

    expect(await screen.findByText("Scored but not ranked")).toBeInTheDocument();
    expect(screen.getByText("Ghost")).toBeInTheDocument();
    expect(screen.getByText("disabled")).toBeInTheDocument();
  });

  it("hides that section entirely when there is nobody in it", async () => {
    render();
    await screen.findByText("Rin");

    expect(screen.queryByText("Scored but not ranked")).not.toBeInTheDocument();
  });

  it("offers a one-click export of the standings as they are", async () => {
    // The full event export is spec 056; this is the more frequent need.
    render();

    expect(await screen.findByRole("button", { name: /export csv/i })).toBeInTheDocument();
  });

  it("says so when nobody has scored", async () => {
    render(board({ players: [], teams: [] }));

    expect((await screen.findAllByText(/nobody has scored/i)).length).toBeGreaterThan(0);
  });
});
