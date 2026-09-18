import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import EventEnding from "./EventEnding";
import type { Me } from "../api/auth";
import type { MyStanding, PlayerEntry, TeamEntry } from "../api/scoreboard";
import type { AchievementsResponse } from "../api/notifications";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const TEAMS: TeamEntry[] = [
  { rank: 1, team_id: "t1", name: "The Mimics", member_count: 4, level: 9, solve_count: 40, last_gain_at: null, stars: [] },
  { rank: 2, team_id: "t2", name: "Kobold Union", member_count: 3, level: 8, solve_count: 30, last_gain_at: null, stars: [] },
  { rank: 3, team_id: "t3", name: "Late Starters", member_count: 2, level: 7, solve_count: 20, last_gain_at: null, stars: [] },
  { rank: 4, team_id: "t4", name: "Also Rans", member_count: 2, level: 6, solve_count: 10, last_gain_at: null, stars: [] },
];

function player(overrides: Partial<PlayerEntry> = {}): PlayerEntry {
  return {
    rank: 1,
    user_id: "p1",
    display_name: "Rin",
    has_avatar: false,
    team_id: null,
    team_name: null,
    level: 9,
    solve_count: 38,
    last_gain_at: null,
    stars: [],
    title: null,
    class_name: null,
    class_rarity: null,
    ...overrides,
  };
}

const SESSION = me({
  capabilities: capabilities({ play: false, blocked_reason: "event_ended" }),
  level: 7,
  total_xp: 8400,
});

interface Fixtures {
  players: PlayerEntry[];
  teams: TeamEntry[];
  standing: MyStanding;
  achievements: AchievementsResponse;
  sheet: { equipped_title: string | null };
  session: Me;
}

function render({
  players = [player({ user_id: SESSION.user.id, display_name: "Grix", rank: 12 })],
  teams = TEAMS,
  standing = { rank: 12, level: 7, player_count: 87, team_rank: 4, team_level: 5, team_count: 21 },
  achievements = {
    earned: 12,
    total: 110,
    items: [],
    rarest: [
      { id: "a1", name: "First Blood", description: null, earned: true, rarity: 0.021 },
    ],
  },
  sheet = { equipped_title: "the Unbothered" },
  session = SESSION,
}: Partial<Fixtures> = {}) {
  stubFetch((path) => {
    if (path.endsWith("/auth/me")) return { status: 200, body: session };
    if (path.includes("/scoreboard/me")) return { status: 200, body: standing };
    if (path.includes("/scoreboard/players")) {
      return { status: 200, body: { total: players.length, generated_at: "x", entries: players } };
    }
    if (path.includes("/scoreboard/teams")) {
      return { status: 200, body: { total: teams.length, generated_at: "x", entries: teams } };
    }
    if (path.endsWith("/character/achievements")) return { status: 200, body: achievements };
    if (path.endsWith("/character/me")) return { status: 200, body: sheet };
    return { status: 200, body: {} };
  });
  renderApp(<EventEnding me={session} />);
}

describe("EventEnding", () => {
  it("shows a podium of three, not the whole board", async () => {
    render();

    // The headings render before the board resolves, so wait on a row.
    await screen.findByText("The Mimics");
    const parties = screen.getByText("Parties").closest("div")!;
    expect(within(parties).getByText("The Mimics")).toBeInTheDocument();
    expect(within(parties).getByText("Late Starters")).toBeInTheDocument();
    // The full board is one link away; this is the moment, not the record.
    expect(within(parties).queryByText("Also Rans")).not.toBeInTheDocument();
  });

  it("shares a place on a tie, and shows no fourth", async () => {
    render({
      teams: [
        { ...TEAMS[0]!, rank: 1 },
        { ...TEAMS[1]!, rank: 2 },
        { ...TEAMS[2]!, name: "Tied A", rank: 2 },
        { ...TEAMS[3]!, name: "Fourth", rank: 4 },
      ],
    });

    await screen.findByText("Tied A");
    const parties = screen.getByText("Parties").closest("div")!;
    // Spec 059 §4.1: the next entry takes the place its position implies.
    expect(within(parties).getByText("Tied A")).toBeInTheDocument();
    expect(within(parties).queryByText("Fourth")).not.toBeInTheDocument();
  });

  it("shows both podiums, because the player board is the one people look at", async () => {
    render();

    expect(await screen.findByText("Parties")).toBeInTheDocument();
    expect(screen.getByText("Players")).toBeInTheDocument();
  });

  it("gives the 87 who did not win something worth reading", async () => {
    render();

    expect(await screen.findByText("Your five days")).toBeInTheDocument();
    expect(await screen.findByText("#12 of 87")).toBeInTheDocument();
    expect(screen.getByText("38")).toBeInTheDocument();
    expect(screen.getByText("12 of 110")).toBeInTheDocument();
  });

  it("shows XP, because this is your own summary in your own chrome", async () => {
    render();

    // The rule is whose and where, not which screen (spec 064 §7.1).
    expect(await screen.findByText("8,400")).toBeInTheDocument();
  });

  it("names the rarest achievement and the title you finished wearing", async () => {
    render();

    expect(await screen.findByText("First Blood")).toBeInTheDocument();
    expect(await screen.findByText("the Unbothered")).toBeInTheDocument();
  });

  it("reads correctly for somebody unranked, partyless and untitled", async () => {
    // The day-five equivalent of day one, and the case most likely to be wrong.
    render({
      players: [],
      teams: [],
      standing: { rank: null, level: 1, player_count: 87, team_rank: null, team_level: null, team_count: 21 },
      achievements: { earned: 0, total: 110, items: [], rarest: [] },
      sheet: { equipped_title: null },
      session: me({
        capabilities: capabilities({ play: false, blocked_reason: "event_ended" }),
        team: null,
      }),
    });

    expect(await screen.findByText("unranked")).toBeInTheDocument();
    expect(screen.getByText("none")).toBeInTheDocument();
    expect(screen.getAllByText("Nobody took the field.")).toHaveLength(2);
  });

  it("keeps the full scoreboard one link away", async () => {
    render();

    expect(await screen.findByRole("link", { name: /full scoreboard/i })).toHaveAttribute(
      "href",
      "/scoreboard",
    );
  });
});
