import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ScoreboardPage from "./ScoreboardPage";
import type { BossStar, PlayerEntry, TeamEntry } from "../api/scoreboard";
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

function star(overrides: Partial<BossStar> = {}): BossStar {
  return { slug: "the-gatekeeper", tier: "city", level: 3, title: "The Gatekeeper", ...overrides };
}

function team(overrides: Partial<TeamEntry> = {}): TeamEntry {
  return {
    rank: 1,
    team_id: "t1",
    name: "The Mimics",
    member_count: 3,
    level: 5,
    solve_count: 8,
    last_gain_at: "2026-09-06T12:00:00Z",
    stars: [],
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
    level: 3,
    solve_count: 4,
    last_gain_at: "2026-09-06T12:00:00Z",
    stars: [],
    title: null,
    class_name: null,
    class_rarity: null,
    ...overrides,
  };
}

/** Eleven parties, so the top-ten framing has something to do. */
function manyTeams(count = 11): TeamEntry[] {
  return Array.from({ length: count }, (_, index) =>
    team({ team_id: `t${index + 1}`, name: `Party ${index + 1}`, rank: index + 1 }),
  );
}

function manyPlayers(count = 11): PlayerEntry[] {
  return Array.from({ length: count }, (_, index) =>
    playerEntry({
      user_id: `u${index + 1}`,
      display_name: `Player ${index + 1}`,
      rank: index + 1,
      team_id: null,
      team_name: null,
    }),
  );
}

function render(
  fallback: { players: PlayerEntry[]; teams: TeamEntry[] } = { players: [], teams: [] },
  session = me(),
) {
  const mock = stubFetch((path) => {
    if (path.endsWith("/auth/me")) return { status: 200, body: session };
    if (path.includes("/scoreboard/players")) {
      return {
        status: 200,
        body: { total: fallback.players.length, generated_at: "x", entries: fallback.players },
      };
    }
    if (/\/scoreboard\/teams\/[^/?]+$/.test(path)) {
      return {
        status: 200,
        body: {
          team_id: "t1",
          name: "The Mimics",
          rank: 1,
          level: 5,
          member_count: 2,
          solve_count: 8,
          achievement_count: 4,
          stars: [star()],
          founded_at: "2026-09-01T00:00:00Z",
          members: [
            {
              user_id: "u1",
              display_name: "Grix",
              has_avatar: false,
              level: 3,
              class_name: "Rogue",
              class_rarity: "rare",
            },
          ],
        },
      };
    }
    return {
      status: 200,
      body: { total: fallback.teams.length, generated_at: "x", entries: fallback.teams },
    };
  });
  renderApp(<ScoreboardPage />);
  return mock;
}

describe("ScoreboardPage", () => {
  it("opens on the party board", async () => {
    render({ players: [], teams: [team()] });

    expect(await screen.findByText("The Mimics")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Parties" })).toHaveAttribute("aria-selected", "true");
  });

  it("explains the union rule, because it is not obvious", async () => {
    render();

    expect(
      await screen.findByText(/party of one and a party of eight can reach the same standing/i),
    ).toBeInTheDocument();
  });

  it("switches to the player board", async () => {
    render({ players: [playerEntry()], teams: [team()] });
    await screen.findByText("The Mimics");

    await userEvent.click(screen.getByRole("tab", { name: "Players" }));

    expect(await screen.findByText("Grix")).toBeInTheDocument();
  });

  it("shows no XP column on either board", async () => {
    render({ players: [playerEntry()], teams: [team()] });
    await screen.findByText("The Mimics");

    // The rule this spec exists for: XP belongs on the player's own sheet.
    expect(screen.queryByText("XP")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Players" }));
    expect(screen.queryByText("XP")).not.toBeInTheDocument();
  });

  describe("top ten, then a break, then you", () => {
    it("shows only the top ten by default", async () => {
      render({ players: [], teams: manyTeams() });
      await screen.findByText("Party 1");

      expect(screen.getByText("Party 10")).toBeInTheDocument();
      expect(screen.queryByText("Party 11")).not.toBeInTheDocument();
    });

    it("pins your party below a break when it is outside the top ten", async () => {
      const rows = manyTeams(40);
      rows[33] = team({ team_id: "mine", name: "Latecomers", rank: 34 });
      render({ players: [], teams: rows }, me({ team: { id: "mine", name: "Latecomers", is_leader: false } }));

      await screen.findByText("Party 1");
      expect(screen.getByText("Latecomers")).toBeInTheDocument();
      // The break says the list skips, rather than leaving it to be inferred
      // from a jump in the rank column — and says so out loud too.
      expect(screen.getByText("Ranks skipped")).toBeInTheDocument();
      expect(screen.getByText("34")).toBeInTheDocument();
    });

    it("adds no break and repeats no row when you are already in the top ten", async () => {
      const rows = manyTeams(40);
      rows[3] = team({ team_id: "mine", name: "Early Risers", rank: 4 });
      render({ players: [], teams: rows }, me({ team: { id: "mine", name: "Early Risers", is_leader: false } }));

      await screen.findByText("Party 1");
      // A duplicate row for somebody at rank 4 would read as two entries.
      expect(screen.getAllByText("Early Risers")).toHaveLength(1);
      expect(screen.queryByText("Ranks skipped")).not.toBeInTheDocument();
    });

    it("shows the top ten and no break to a viewer with no party", async () => {
      render({ players: [], teams: manyTeams(40) }, me({ team: null }));

      await screen.findByText("Party 1");
      expect(screen.queryByText("Ranks skipped")).not.toBeInTheDocument();
      expect(screen.queryByText("Party 11")).not.toBeInTheDocument();
    });

    it("expands to every row without a further request", async () => {
      const fetchMock = render({ players: [], teams: manyTeams(40) });
      await screen.findByText("Party 1");
      const before = fetchMock.mock.calls.length;

      await userEvent.click(screen.getByRole("button", { name: "Show all 40" }));

      expect(screen.getByText("Party 40")).toBeInTheDocument();
      // The payload is the whole board already, so paging it would mean asking
      // the server for what it has sent.
      expect(fetchMock.mock.calls.length).toBe(before);
    });

    it("collapses back to the top ten", async () => {
      render({ players: [], teams: manyTeams(40) });
      await screen.findByText("Party 1");
      await userEvent.click(screen.getByRole("button", { name: "Show all 40" }));

      await userEvent.click(screen.getByRole("button", { name: "Show the top 10" }));

      expect(screen.queryByText("Party 11")).not.toBeInTheDocument();
    });

    it("offers no expansion when the board is shorter than ten", async () => {
      render({ players: [], teams: manyTeams(4) });
      await screen.findByText("Party 1");

      expect(screen.queryByRole("button", { name: /show all/i })).not.toBeInTheDocument();
    });
  });

  describe("search", () => {
    it("shows matches with their real ranks, ignoring the top ten", async () => {
      const rows = manyTeams(40);
      render({ players: [], teams: rows });
      await screen.findByText("Party 1");

      await userEvent.type(screen.getByLabelText("Search parties"), "Party 34");

      // "Rank 34 of 40" is the useful answer to a search; "no results in the
      // top ten" is not.
      const row = screen.getByText("Party 34").closest("tr")!;
      expect(within(row).getByText("34")).toBeInTheDocument();
      expect(screen.queryByText("Party 1")).not.toBeInTheDocument();
      expect(screen.queryByText("Ranks skipped")).not.toBeInTheDocument();
    });

    it("searches players by name", async () => {
      render({ players: manyPlayers(20), teams: [] });
      await userEvent.click(await screen.findByRole("tab", { name: "Players" }));

      await userEvent.type(screen.getByLabelText("Search players"), "Player 17");

      expect(screen.getByText("Player 17")).toBeInTheDocument();
      expect(screen.queryByText("Player 1")).not.toBeInTheDocument();
    });

    it("says so when nothing matches", async () => {
      render({ players: [], teams: manyTeams(4) });
      await screen.findByText("Party 1");

      await userEvent.type(screen.getByLabelText("Search parties"), "zzzz");

      expect(screen.getByText(/nobody by that name/i)).toBeInTheDocument();
    });
  });

  describe("boss stars", () => {
    it("carries a total and a per-tier breakdown in its label, and names each boss", async () => {
      render({
        players: [],
        teams: [
          team({
            stars: [
              star({ slug: "the-floor", tier: "floor", level: 6, title: "The Floor" }),
              star({ slug: "xyz", tier: "city", level: 3, title: "XYZ" }),
              star({ slug: "abc", tier: "city", level: 3, title: "ABC" }),
            ],
          }),
        ],
      });

      // Colour is never the only carrier, and six colours side by side is
      // exactly where that earns its keep.
      const run = await screen.findByRole("img", {
        name: "3 bosses felled: 1 floor, 2 city",
      });
      expect(run).toBeInTheDocument();
      expect(within(run).getByTitle("The Floor · floor")).toBeInTheDocument();
    });

    it("shows a dash rather than an empty run when nothing has been felled", async () => {
      render({ players: [], teams: [team({ stars: [] })] });

      const row = (await screen.findByText("The Mimics")).closest("tr")!;
      expect(within(row).getByText("—")).toBeInTheDocument();
    });

    it("shows the player's own stars on the player board", async () => {
      render({ players: [playerEntry({ stars: [star()] })], teams: [] });
      await userEvent.click(await screen.findByRole("tab", { name: "Players" }));

      // Their own kills, never their party's.
      expect(screen.getByRole("img", { name: "1 boss felled: 1 city" })).toBeInTheDocument();
    });
  });

  describe("where a row leads", () => {
    it("opens the party panel from a party row", async () => {
      render({ players: [], teams: [team()] });

      await userEvent.click(await screen.findByRole("button", { name: "The Mimics" }));

      const panel = await screen.findByRole("dialog", { name: "Party detail" });
      expect(within(panel).getByText("Rank 1 · Level 5")).toBeInTheDocument();
      expect(within(panel).getByText("Grix")).toBeInTheDocument();
      expect(within(panel).getByText("Rogue")).toBeInTheDocument();
    });

    it("opens the same panel from the player board's Party column", async () => {
      render({ players: [playerEntry()], teams: [team()] });
      await userEvent.click(await screen.findByRole("tab", { name: "Players" }));

      await userEvent.click(screen.getByRole("button", { name: "The Mimics" }));

      expect(await screen.findByRole("dialog", { name: "Party detail" })).toBeInTheDocument();
    });

    it("shows no XP for the party or anybody in it", async () => {
      render({ players: [], teams: [team()] });
      await userEvent.click(await screen.findByRole("button", { name: "The Mimics" }));
      const panel = await screen.findByRole("dialog", { name: "Party detail" });

      expect(within(panel).queryByText(/\bXP\b/)).not.toBeInTheDocument();
      // Solves, awards and adventurers — all the things that are not XP.
      expect(within(panel).getByText("Solved")).toBeInTheDocument();
      expect(within(panel).getByText("Awards")).toBeInTheDocument();
    });

    it("closes the panel on Escape", async () => {
      render({ players: [], teams: [team()] });
      await userEvent.click(await screen.findByRole("button", { name: "The Mimics" }));
      await screen.findByRole("dialog", { name: "Party detail" });

      await userEvent.keyboard("{Escape}");

      await waitFor(() =>
        expect(screen.queryByRole("dialog", { name: "Party detail" })).not.toBeInTheDocument(),
      );
    });

    it("links a player through to their character sheet", async () => {
      render({ players: [playerEntry()], teams: [] });
      await userEvent.click(await screen.findByRole("tab", { name: "Players" }));

      // A sheet rather than a panel: duplicating a fraction of it would be a
      // second thing to keep true.
      expect(screen.getByRole("link", { name: /Grix/ })).toHaveAttribute(
        "href",
        "/character/u1",
      );
    });
  });

  describe("what the player board showcases", () => {
    it("shows the worn loot title and the class with its rarity colour", async () => {
      render({
        players: [
          playerEntry({ title: "the Unbothered", class_name: "Rogue", class_rarity: "rare" }),
        ],
        teams: [],
      });
      await userEvent.click(await screen.findByRole("tab", { name: "Players" }));

      expect(screen.getByText("the Unbothered")).toBeInTheDocument();
      // The rarity's name is the class name here; the colour is an addition to
      // it, never the only signal.
      expect(screen.getByText("Rogue").className).toContain("text-rarity-rare");
    });

    it("falls back rather than throwing on an unrecognised rarity", async () => {
      render({
        players: [playerEntry({ class_name: "Voidwalker", class_rarity: "transcendent" })],
        teams: [],
      });
      await userEvent.click(await screen.findByRole("tab", { name: "Players" }));

      expect(screen.getByText("Voidwalker").className).toContain("text-content-muted");
    });
  });

  describe("the live socket", () => {
    it("replaces the fetched board with the pushed one", async () => {
      render({ players: [], teams: [team({ name: "Stale" })] });
      await screen.findByText("Stale");

      const socket = FakeSocket.instances[0]!;
      socket.open();
      socket.send({
        generated_at: "2026-09-06T12:00:01Z",
        players: [],
        teams: [team({ name: "Fresh" })],
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
  });

  it("marks your own party", async () => {
    render(
      { players: [], teams: [team(), team({ team_id: "t2", name: "Others", rank: 2 })] },
      me({ team: { id: "t1", name: "The Mimics", is_leader: false } }),
    );

    const row = (await screen.findByText("The Mimics")).closest("tr")!;
    expect(row.className).toContain("bg-accent/10");
    expect(within(row).getByText("you")).toBeInTheDocument();
  });

  it("marks you on the player board", async () => {
    render(
      { players: [playerEntry({ user_id: "me-1", display_name: "Mine" })], teams: [] },
      me({ user: { ...me().user, id: "me-1" } }),
    );
    await userEvent.click(await screen.findByRole("tab", { name: "Players" }));

    const row = screen.getByText("Mine").closest("tr")!;
    expect(within(row).getByText("you")).toBeInTheDocument();
  });

  it("says so when nobody has taken the field", async () => {
    render();

    expect(await screen.findByText(/no parties have taken the field yet/i)).toBeInTheDocument();
  });

  it("shows how many adventurers are in each party", async () => {
    render({ players: [], teams: [team({ member_count: 1 })] });

    const row = (await screen.findByText("The Mimics")).closest("tr")!;
    // Singular, because "1 adventurers" reads like a bug.
    expect(within(row).getByText(/1 adventurer ·/)).toBeInTheDocument();
  });
});
