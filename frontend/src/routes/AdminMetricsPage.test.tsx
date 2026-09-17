import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminMetricsPage from "./AdminMetricsPage";
import type { ChallengeMetric, StalledPlayer } from "../api/adminMetrics";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function challenge(overrides: Partial<ChallengeMetric> = {}): ChallengeMetric {
  return {
    challenge_id: "c1",
    title: "Sealed Vault",
    zone: "Crypto",
    difficulty: "medium",
    state: "published",
    attempts: 40,
    solves: 4,
    attempts_per_solve: 10,
    vs_difficulty: 2.5,
    hint_uptake: 3,
    near_miss_rate: 0.35,
    ...overrides,
  };
}

function player(overrides: Partial<StalledPlayer> = {}): StalledPlayer {
  return {
    user_id: "u1",
    display_name: "Rin",
    solves: 4,
    xp: 480,
    level: 3,
    last_solve_at: null,
    last_submission_at: new Date().toISOString(),
    current_wall: "Sealed Vault",
    hints_used: 0,
    ...overrides,
  };
}

/** The challenges table, which shares names with the players table below it. */
function challengeRow(title: string): HTMLElement {
  const table = screen.getAllByRole("table")[0]!;
  return within(table).getByText(title).closest("tr")!;
}

function render({
  challenges = [challenge()],
  players = [player()],
}: { challenges?: ChallengeMetric[]; players?: StalledPlayer[] } = {}) {
  const mock = stubFetch((path) => {
    if (path.endsWith("/auth/me")) {
      return { status: 200, body: me({ user: { ...me().user, role: "organizer" } }) };
    }
    if (path.includes("/metrics/pulse")) {
      return {
        status: 200,
        body: {
          window: "today",
          solves: 42,
          solves_previous: 30,
          solves_per_hour: 1.8,
          attempts_per_solve: 3.4,
          wrong_attempts: 101,
          active_players: 40,
          approved_players: 200,
          participation: 0.2,
          hints_unlocked: 12,
          first_time_solvers: 5,
          generated_at: "2026-09-17T12:00:00Z",
        },
      };
    }
    if (path.includes("/metrics/challenges")) {
      return { status: 200, body: { window: "today", challenges, generated_at: "x" } };
    }
    if (path.includes("/metrics/players")) {
      return { status: 200, body: { filter: "stuck", players, generated_at: "x" } };
    }
    if (path.includes("/metrics/progression")) {
      return {
        status: 200,
        body: {
          levels: [{ level: 3, players: 12 }],
          zone_spread: [{ zone: "Crypto", players: 20 }],
          category_health: [
            { zone: "Crypto", attempts: 100, solves: 10, attempts_per_solve: 10 },
          ],
          hints: { unlocked: 12, players_using: 7, hints_per_solve: 0.28 },
          generated_at: "x",
        },
      };
    }
    return { status: 200, body: {} };
  });
  renderApp(<AdminMetricsPage />);
  return mock;
}

describe("AdminMetricsPage", () => {
  it("leads with attempts per solve, the early warning", async () => {
    render();

    expect(await screen.findByText("Attempts per solve")).toBeInTheDocument();
    expect(screen.getByText("3.4")).toBeInTheDocument();
  });

  it("shows participation against the approved roster, not as a bare count", async () => {
    // 40 active out of 200 approved is a different event from 40 out of 45.
    render();

    expect(await screen.findByText("20%")).toBeInTheDocument();
    expect(screen.getByText(/of 200 approved/)).toBeInTheDocument();
  });

  it("gives a rate a direction", async () => {
    render();

    expect(await screen.findByText("+12 vs previous")).toBeInTheDocument();
  });

  it("flags a challenge drifting past its difficulty band", async () => {
    render();
    await screen.findAllByText("Sealed Vault");

    expect(within(challengeRow("Sealed Vault")).getByText("2.5×")).toHaveClass("text-warning");
  });

  it("shows a dash rather than a made-up multiple below the attempt floor", async () => {
    // Early in an event most challenges look like this.
    render({ challenges: [challenge({ vs_difficulty: null, attempts: 3 })] });
    await screen.findAllByText("Sealed Vault");

    expect(
      within(challengeRow("Sealed Vault")).getByTitle(/not enough attempts/i),
    ).toBeInTheDocument();
  });

  it("shows the near-miss rate as a rate and never an example", async () => {
    render();
    await screen.findAllByText("Sealed Vault");

    expect(within(challengeRow("Sealed Vault")).getByText("35%")).toBeInTheDocument();
  });

  it("names the wall a stalled player is up against", async () => {
    render();
    const row = (await screen.findByText("Rin")).closest("tr")!;

    expect(within(row).getAllByText("Sealed Vault").length).toBeGreaterThan(0);
    expect(within(row).getByText("never")).toBeInTheDocument();
  });

  it("says the window control does not apply to the stalled bands", async () => {
    render();

    expect(await screen.findByText(/window above does not apply/i)).toBeInTheDocument();
  });

  it("switches the stalled filter server-side", async () => {
    const fetchMock = render();
    await screen.findByText("Rin");

    await userEvent.click(screen.getByRole("button", { name: "Never started" }));

    expect(
      fetchMock.mock.calls.some(([path]) => String(path).includes("filter=never_started")),
    ).toBe(true);
  });

  it("changes the window server-side", async () => {
    const fetchMock = render();
    await screen.findByText("Attempts per solve");

    await userEvent.click(screen.getByRole("button", { name: "Last hour" }));

    expect(fetchMock.mock.calls.some(([path]) => String(path).includes("window=1h"))).toBe(true);
  });

  it("puts a number beside every bar, so nothing rides on length alone", async () => {
    render();

    // "Crypto" is also a challenge's zone column; the bar is the one in a list.
    const bars = (await screen.findAllByText("Crypto")).map((node) => node.closest("li"));
    const zone = bars.find((node) => node !== null)!;
    expect(within(zone).getByText("20")).toBeInTheDocument();
  });
});
