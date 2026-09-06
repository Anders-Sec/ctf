import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ScoreboardPage from "./ScoreboardPage";
import type { PlayerEntry, TeamEntry } from "../api/scoreboard";
import { me, renderApp, stubFetch } from "../test/utils";

/** A WebSocket stand-in whose messages the test drives by hand. */
class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }

  open() {
    this.onopen?.();
  }

  send(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  sendRaw(data: string) {
    this.onmessage?.({ data });
  }

  close() {
    this.closed = true;
    this.onclose?.();
  }
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket as unknown as typeof WebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function team(overrides: Partial<TeamEntry> = {}): TeamEntry {
  return {
    rank: 1,
    team_id: "t1",
    name: "The Mimics",
    member_count: 3,
    score: 800,
    solve_count: 8,
    last_gain_at: "2026-09-06T12:00:00Z",
    ...overrides,
  };
}

function playerEntry(overrides: Partial<PlayerEntry> = {}): PlayerEntry {
  return {
    rank: 1,
    user_id: "u1",
    display_name: "Grix",
    has_avatar: false,
    team_id: "t1",
    team_name: "The Mimics",
    score: 400,
    solve_count: 4,
    last_gain_at: "2026-09-06T12:00:00Z",
    ...overrides,
  };
}

function render(fallback: { players: PlayerEntry[]; teams: TeamEntry[] } = { players: [], teams: [] }) {
  stubFetch((path) => {
    if (path.endsWith("/auth/me")) return { status: 200, body: me() };
    if (path.includes("/scoreboard/players")) {
      return {
        status: 200,
        body: { total: fallback.players.length, generated_at: "x", entries: fallback.players },
      };
    }
    return {
      status: 200,
      body: { total: fallback.teams.length, generated_at: "x", entries: fallback.teams },
    };
  });
  return renderApp(<ScoreboardPage />);
}

describe("ScoreboardPage", () => {
  it("opens on the party board", async () => {
    render({ players: [], teams: [team()] });

    expect(await screen.findByText("The Mimics")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Parties" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("explains the union rule, because it is not obvious", async () => {
    render();

    expect(
      await screen.findByText(/party of one and a party of eight can reach the same total/i),
    ).toBeInTheDocument();
  });

  it("switches to the player board", async () => {
    render({ players: [playerEntry()], teams: [team()] });
    await screen.findByText("The Mimics");

    await userEvent.click(screen.getByRole("tab", { name: "Players" }));

    expect(await screen.findByText("Grix")).toBeInTheDocument();
  });

  it("replaces the fetched board with the pushed one", async () => {
    render({ players: [], teams: [team({ name: "Stale", score: 100 })] });
    await screen.findByText("Stale");

    const socket = FakeSocket.instances[0]!;
    socket.open();
    socket.send({
      generated_at: "2026-09-06T12:00:01Z",
      players: [],
      teams: [team({ name: "Fresh", score: 900 })],
    });

    expect(await screen.findByText("Fresh")).toBeInTheDocument();
    expect(screen.queryByText("Stale")).not.toBeInTheDocument();
  });

  it("reports the connection state", async () => {
    render();
    const socket = FakeSocket.instances[0]!;

    socket.open();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("live"));

    socket.close();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/reconnecting/i));
  });

  it("reconnects after a drop", async () => {
    vi.useFakeTimers();
    render();
    const first = FakeSocket.instances[0]!;
    first.open();

    first.close();
    await vi.advanceTimersByTimeAsync(1500);

    expect(FakeSocket.instances.length).toBeGreaterThan(1);
  });

  it("survives a malformed frame without tearing down", async () => {
    render({ players: [], teams: [team({ name: "Intact" })] });
    await screen.findByText("Intact");

    const socket = FakeSocket.instances[0]!;
    socket.open();
    socket.sendRaw("not json");

    expect(screen.getByText("Intact")).toBeInTheDocument();
    expect(socket.closed).toBe(false);
  });

  it("highlights your own party", async () => {
    stubFetch((path) => {
      if (path.endsWith("/auth/me")) {
        return {
          status: 200,
          body: me({ team: { id: "t1", name: "The Mimics", is_leader: false } }),
        };
      }
      if (path.includes("/scoreboard/players")) {
        return { status: 200, body: { total: 0, generated_at: "x", entries: [] } };
      }
      return {
        status: 200,
        body: {
          total: 2,
          generated_at: "x",
          entries: [team(), team({ team_id: "t2", name: "Others", rank: 2 })],
        },
      };
    });
    renderApp(<ScoreboardPage />);

    const row = (await screen.findByText("The Mimics")).closest("tr")!;
    expect(row.className).toContain("bg-ink/5");
  });

  it("says so when nobody has scored", async () => {
    render();

    expect(await screen.findByText(/no parties have scored yet/i)).toBeInTheDocument();
  });

  it("shows how many adventurers are in each party", async () => {
    render({ players: [], teams: [team({ member_count: 1 })] });

    const row = (await screen.findByText("The Mimics")).closest("tr")!;
    // Singular, because "1 adventurers" reads like a bug.
    expect(within(row).getByText(/1 adventurer$/)).toBeInTheDocument();
  });
});
