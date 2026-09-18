import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import HomePage, { firstOpenZone, whereYouLeftOff } from "./HomePage";
import type { ChallengeListItem } from "../api/challenges";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  // The tour and the checklist both remember themselves per browser.
  localStorage.clear();
  localStorage.setItem("ctf.tour.seen", "1");
});

function withSession(overrides: Parameters<typeof me>[0]) {
  stubFetch(() => ({ status: 200, body: me(overrides) }));
  renderApp(<HomePage />);
}

function challenge(overrides: Partial<ChallengeListItem> = {}): ChallengeListItem {
  return {
    id: "c1",
    title: "Port of Call",
    slug: "port-of-call",
    category: { id: "z1", name: "Networking", slug: "networking", description: null, display_order: 0 },
    difficulty: "very_easy",
    state: "published",
    locked: false,
    value: 50,
    solve_count: 3,
    solved: false,
    attempts_remaining: null,
    max_attempts: null,
    release_at: null,
    unlock_requirements: [],
    puzzle_kind: null,
    puzzle_status: null,
    ...overrides,
  };
}

/** A playing session, with every endpoint the page reaches for. */
function playing({
  challenges = [challenge()],
  solves = [] as { category: string; solved_at: string; challenge_id: string; title: string; value: number }[],
  standing = { rank: 12, level: 7, player_count: 87, team_rank: 4, team_level: 5, team_count: 21 },
  sheet = {},
  session = {},
} = {}) {
  stubFetch((path) => {
    if (path.endsWith("/auth/me")) {
      return {
        status: 200,
        body: me({ capabilities: capabilities({ play: true }), ...session }),
      };
    }
    if (path.endsWith("/me/score")) return { status: 200, body: { total: 0, solves } };
    if (path.includes("/scoreboard/me")) return { status: 200, body: standing };
    if (path.endsWith("/character/me")) {
      return {
        status: 200,
        body: {
          skills: [],
          character_class: null,
          class_unlocked: false,
          class_unlock_level: 5,
          ...sheet,
        },
      };
    }
    if (path.includes("/challenges")) return { status: 200, body: challenges };
    return { status: 200, body: {} };
  });
  renderApp(<HomePage />);
}

describe("HomePage gates", () => {
  it("tells a pending guest they are waiting on approval", async () => {
    withSession({
      capabilities: capabilities({
        play: false,
        view_scoreboard: false,
        blocked_reason: "account_pending_approval",
      }),
    });

    expect(await screen.findByText(/Awaiting approval/i)).toBeInTheDocument();
  });

  it("still points a pending guest at forming a party", async () => {
    // Only gameplay waits on approval, so the party route stays useful.
    withSession({
      capabilities: capabilities({ play: false, blocked_reason: "account_pending_approval" }),
    });

    expect(await screen.findByText(/join a party in the meantime/i)).toBeInTheDocument();
  });

  it("shows the start time before the doors open", async () => {
    withSession({
      capabilities: capabilities({ play: false, blocked_reason: "event_not_started" }),
    });

    expect(await screen.findByText(/doors are still shut/i)).toBeInTheDocument();
  });

  it("distinguishes a finished event from one that has not begun", async () => {
    withSession({
      capabilities: capabilities({ play: false, blocked_reason: "event_ended" }),
    });

    expect(await screen.findByText(/crawl is over/i)).toBeInTheDocument();
  });

  it("reports a disabled account", async () => {
    withSession({
      capabilities: capabilities({
        play: false,
        manage_party: false,
        blocked_reason: "account_disabled",
      }),
    });

    expect(await screen.findByText(/account is disabled/i)).toBeInTheDocument();
  });

  it("shows no cards to somebody who may not play", async () => {
    withSession({
      capabilities: capabilities({ play: false, blocked_reason: "account_pending_approval" }),
    });
    await screen.findByText(/Awaiting approval/i);

    expect(screen.queryByText("Where you left off")).not.toBeInTheDocument();
    expect(screen.queryByText("Your standing")).not.toBeInTheDocument();
  });
});

describe("HomePage, playing", () => {
  it("answers how you are doing without opening the scoreboard", async () => {
    playing();

    expect(await screen.findByText("Your standing")).toBeInTheDocument();
    expect(await screen.findByText("#12")).toBeInTheDocument();
    expect(screen.getByText("#4")).toBeInTheDocument();
  });

  it("puts no XP figure on the page", async () => {
    playing();
    await screen.findByText("Your standing");

    // Level is the public shape of the same fact (spec 059). The rule is about
    // showing the number, not the word — the checklist's hint mentions XP as
    // the thing that earns a skill, which is guidance rather than a score.
    expect(screen.queryByText(/\d[\d,]*\s*XP/)).not.toBeInTheDocument();
  });

  it("names the party the player marches with", async () => {
    playing({ session: { team: { id: "t1", name: "The Mimics", is_leader: true } } });

    expect(await screen.findByText("The Mimics")).toBeInTheDocument();
    expect(screen.getByText(/you lead it/i)).toBeInTheDocument();
  });

  it("points a partyless player at finding one", async () => {
    playing({ session: { team: null } });

    expect(await screen.findByText(/No party yet/i)).toBeInTheDocument();
  });

  it("picks up where you left off", async () => {
    playing({
      challenges: [
        challenge({ id: "a", title: "Port of Call", solved: true }),
        challenge({ id: "b", title: "No Place Like It", value: 50 }),
      ],
      solves: [
        {
          challenge_id: "a",
          title: "Port of Call",
          category: "Networking",
          value: 50,
          solved_at: "2026-09-18T10:00:00Z",
        },
      ],
    });

    const card = (await screen.findByText("Where you left off")).closest("section")!;
    expect(await within(card).findByText("Networking")).toBeInTheDocument();
    expect(within(card).getByText("1/2")).toBeInTheDocument();
    // The board's own order is the server's since spec 062, so this is the same
    // row the board would show first.
    expect(within(card).getByRole("link", { name: "No Place Like It" })).toHaveAttribute(
      "href",
      "/challenges/b",
    );
  });

  it("says so before the first solve rather than showing an empty card", async () => {
    playing();

    const card = (await screen.findByText("Where you left off")).closest("section")!;
    expect(within(card).getByText(/Nothing yet/)).toBeInTheDocument();
  });
});

describe("first steps", () => {
  it("ticks what is done and links what is not", async () => {
    playing({ session: { team: { id: "t1", name: "The Mimics", is_leader: false } } });

    const panel = (await screen.findByText("First steps")).closest("section")!;
    expect(await within(panel).findByText("2 of 5")).toBeInTheDocument();
    // "Go and solve something" is not guidance, so the step names a zone.
    expect(within(panel).getByText(/start in Networking/)).toBeInTheDocument();
  });

  it("shows the class step greyed with its level rather than hiding it", async () => {
    playing();

    const panel = (await screen.findByText("First steps")).closest("section")!;
    // Knowing there is more is the point (spec 066 §3.1).
    expect(within(panel).getByText("Choose a class")).toBeInTheDocument();
    expect(within(panel).getByText("(level 5)")).toBeInTheDocument();
    expect(within(panel).queryByRole("link", { name: "Choose a class" })).toBeNull();
  });

  it("disappears once every step is done, and stays gone", async () => {
    playing({
      challenges: [challenge({ solved: true })],
      session: { team: { id: "t1", name: "The Mimics", is_leader: false } },
      sheet: {
        skills: [{ skill_id: "s1", name: "Packet Reading", kind: "useful", level: 2, discovered: true }],
        character_class: { id: "c1", name: "Rogue", description: null, rarity: "common" },
        class_unlocked: true,
        class_unlock_level: 5,
      },
    });

    // Wait for every query the checklist reads before asserting it is gone.
    await screen.findByText("#12");
    await waitFor(() =>
      expect(screen.queryByText("First steps")).not.toBeInTheDocument(),
    );
    // A checklist that comes back because somebody left a party reads as an
    // accusation (spec 066 §7.1).
    expect(localStorage.getItem("ctf.firstSteps.done")).toBe("1");
  });
});

describe("whereYouLeftOff", () => {
  it("takes the most recent solve, not the first", () => {
    const rows = [
      challenge({ id: "a", category: { id: "z1", name: "Networking", slug: "networking", description: null, display_order: 0 } }),
      challenge({ id: "b", category: { id: "z2", name: "Crypto", slug: "crypto", description: null, display_order: 1 } }),
    ];
    const solves = [
      { category: "Networking", solved_at: "2026-09-18T09:00:00Z" },
      { category: "Crypto", solved_at: "2026-09-18T11:00:00Z" },
    ];

    expect(whereYouLeftOff(rows, solves)?.zone.name).toBe("Crypto");
  });

  it("skips a locked row when choosing the next one", () => {
    const zone = { id: "z1", name: "Networking", slug: "networking", description: null, display_order: 0 };
    const rows = [
      challenge({ id: "a", category: zone, solved: true }),
      challenge({ id: "b", category: zone, locked: true, title: null }),
      challenge({ id: "c", category: zone, title: "Open One" }),
    ];

    const next = whereYouLeftOff(rows, [
      { category: "Networking", solved_at: "2026-09-18T09:00:00Z" },
    ])?.next;

    expect(next?.id).toBe("c");
  });

  it("is null with nothing solved", () => {
    expect(whereYouLeftOff([challenge()], [])).toBeNull();
  });
});

describe("firstOpenZone", () => {
  it("names the first zone holding something unlocked and unsolved", () => {
    expect(firstOpenZone([challenge()])?.name).toBe("Networking");
  });

  it("is null when everything is sealed", () => {
    expect(firstOpenZone([challenge({ locked: true })])).toBeNull();
  });
});
