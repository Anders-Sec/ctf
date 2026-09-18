import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ChallengesPage from "./ChallengesPage";
import type { ChallengeListItem } from "../api/challenges";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function challenge(overrides: Partial<ChallengeListItem> = {}): ChallengeListItem {
  return {
    id: "c1",
    title: "Packet Puzzle",
    slug: "packet-puzzle",
    category: {
      id: "cat1",
      name: "Forensics",
      slug: "forensics",
      description: null,
      display_order: 0,
    },
    difficulty: "medium",
    state: "published",
    locked: false,
    value: 420,
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

function withBoard(challenges: ChallengeListItem[], total = 0) {
  stubFetch((path) => {
    if (path.endsWith("/auth/me")) return { status: 200, body: me() };
    if (path.endsWith("/me/score")) return { status: 200, body: { total, solves: [] } };
    return { status: 200, body: challenges };
  });
  renderApp(<ChallengesPage />);
}

// The list is the board's default since spec 062, so nothing needs pinning —
// but the collapse state is remembered per browser and would leak between tests.
beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

describe("ChallengesPage", () => {
  it("shows a challenge with its current value", async () => {
    withBoard([challenge()]);

    expect(await screen.findByText("Packet Puzzle")).toBeInTheDocument();
    expect(screen.getByText("420")).toBeInTheDocument();
  });

  it("shows the player's running total", async () => {
    withBoard([challenge()], 1250);

    expect(await screen.findByLabelText("Your XP")).toHaveTextContent("1250");
  });

  it("marks solved challenges", async () => {
    withBoard([challenge({ solved: true })]);
    await screen.findByText("Packet Puzzle");

    const row = screen.getByText("Packet Puzzle").closest("li")!;
    expect(within(row).getByText("✓")).toBeInTheDocument();
  });

  it("names the difficulty in words, never as a database value", async () => {
    withBoard([challenge({ difficulty: "very_easy" })]);

    expect(await screen.findByText("Very Easy")).toBeInTheDocument();
    expect(screen.queryByText("very_easy")).not.toBeInTheDocument();
  });

  it("opens a challenge without leaving the board", async () => {
    withBoard([challenge()]);

    await userEvent.click(await screen.findByRole("button", { name: /Packet Puzzle/ }));

    // The list is still mounted behind the overlay, which is what makes the
    // scroll position survive by construction (spec 062 §5).
    expect(screen.getByRole("heading", { name: "Challenges" })).toBeInTheDocument();
  });

  it("groups challenges by zone, in the order the server sent", async () => {
    withBoard([
      challenge({
        id: "a",
        title: "Web One",
        category: { id: "w", name: "Web", slug: "web", description: null, display_order: 0 },
      }),
      challenge({ id: "b", title: "Forensics One" }),
    ]);

    await screen.findByText("Web One");
    const board = screen.getByRole("region", { name: "Challenge board" });
    // The heading, not the row: "Web One" also matches /Web/.
    const web = within(board).getByRole("heading", { name: /Web/ }).closest("section")!;
    expect(within(web).getByText("Web One")).toBeInTheDocument();
    expect(within(web).queryByText("Forensics One")).not.toBeInTheDocument();
  });

  it("collapses a zone, keeping its progress visible", async () => {
    withBoard([challenge({ solved: true })]);
    await screen.findByText("Packet Puzzle");

    const board = screen.getByRole("region", { name: "Challenge board" });
    // The button inside the heading — clicking the h2 itself reaches nothing.
    const heading = within(board).getByRole("heading", { name: /Forensics/ });
    await userEvent.click(within(heading).getByRole("button"));

    expect(screen.queryByText("Packet Puzzle")).not.toBeInTheDocument();
    // A shut group still says what is inside it.
    expect(screen.getAllByText("1/1").length).toBeGreaterThan(0);
  });

  it("lists every zone in the sidebar with its progress", async () => {
    withBoard([challenge({ id: "a", solved: true }), challenge({ id: "b", title: "Second" })]);
    await screen.findByText("Packet Puzzle");

    // Spec 019 gates zones on percent cleared, so this is the number a player
    // would otherwise count by hand.
    const sidebar = screen.getAllByRole("navigation", { name: "Zones" })[0]!;
    expect(within(sidebar).getByText("1/2")).toBeInTheDocument();
  });

  describe("sealed content", () => {
    it("collapses a wholly sealed zone to one row", async () => {
      withBoard([
        challenge({
          id: "a",
          title: null,
          slug: null,
          locked: true,
          value: 300,
          unlock_requirements: [
            {
              type: "percent_in_category",
              met: false,
              description: "Clear 70% of Web Attacks",
              challenge_id: null,
              title: null,
              threshold: 70,
              progress: 40,
            },
          ],
        }),
        challenge({ id: "b", title: null, slug: null, locked: true, value: 200 }),
      ]);

      // No per-challenge rows at all — the size is the carrot, and it gives
      // away nothing about what is in there (spec 062 §4.1).
      expect(await screen.findByText("Clear 70% of Web Attacks")).toBeInTheDocument();
      expect(screen.getByText(/2 challenges · 500 XP/)).toBeInTheDocument();
      // The requirement list is itself a <ul>, so the assertion is about
      // challenge rows specifically: there are none.
      expect(screen.queryByText("A sealed challenge")).not.toBeInTheDocument();
    });

    it("shows a sealed row's size and criteria, and no name", async () => {
      withBoard([
        challenge({ id: "a", title: "Open One" }),
        challenge({
          id: "b",
          title: null,
          slug: null,
          locked: true,
          value: 350,
          difficulty: "hard",
          unlock_requirements: [
            {
              type: "challenge_solved",
              met: false,
              description: "Solve Open One first",
              challenge_id: "a",
              title: "Open One",
              threshold: null,
              progress: null,
            },
          ],
        }),
      ]);

      await screen.findByText("Open One");
      expect(screen.getByText("A sealed challenge")).toBeInTheDocument();
      expect(screen.getByText("Solve Open One first")).toBeInTheDocument();
      // How big and how hard it is, is the carrot. The name is the content.
      expect(screen.getByText("350")).toBeInTheDocument();
      expect(screen.getByText("Hard")).toBeInTheDocument();
    });

    it("cannot find a sealed challenge by search", async () => {
      withBoard([
        challenge({ id: "a", title: "Open One" }),
        challenge({ id: "b", title: null, slug: null, locked: true }),
      ]);
      await screen.findByText("Open One");

      await userEvent.type(screen.getByLabelText("Search challenges"), "o");

      // There is no name to match: the server sent none.
      expect(screen.queryByText("A sealed challenge")).not.toBeInTheDocument();
    });
  });

  it("can hide solved challenges", async () => {
    withBoard([
      challenge({ id: "a", title: "Done", solved: true }),
      challenge({ id: "b", title: "Todo" }),
    ]);
    await screen.findByText("Done");

    await userEvent.click(screen.getByLabelText(/hide solved/i));

    expect(screen.queryByText("Done")).not.toBeInTheDocument();
    expect(screen.getByText("Todo")).toBeInTheDocument();
  });

  it("reports remaining attempts when a challenge is capped", async () => {
    withBoard([challenge({ max_attempts: 3, attempts_remaining: 2 })]);

    expect(await screen.findByText(/2 of 3 left/i)).toBeInTheDocument();
  });

  it("opens on the list rather than the map", async () => {
    withBoard([challenge()]);

    expect(await screen.findByRole("button", { name: "List" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("keeps the map one toggle away", async () => {
    withBoard([challenge()]);

    await userEvent.click(await screen.findByRole("button", { name: "Map" }));

    expect(screen.getByRole("button", { name: "Map" })).toHaveAttribute("aria-pressed", "true");
  });

  it("says so when nothing is available yet", async () => {
    withBoard([]);

    expect(await screen.findByText(/nothing has been unsealed/i)).toBeInTheDocument();
  });
});
