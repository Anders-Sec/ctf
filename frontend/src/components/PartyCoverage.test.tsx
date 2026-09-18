import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import PartyCoverage from "./PartyCoverage";
import type { ChallengeListItem } from "../api/challenges";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function challenge(overrides: Partial<ChallengeListItem> = {}): ChallengeListItem {
  return {
    id: "c1",
    title: "Port of Call",
    slug: "port-of-call",
    category: {
      id: "z1",
      name: "Networking",
      slug: "networking",
      description: null,
      display_order: 0,
    },
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

const ZONES = [
  { name: "Networking", slug: "networking", cleared: 1, total: 2, sealed: false },
  { name: "The Vaults", slug: "vaults", cleared: 0, total: 6, sealed: true },
];

function render({
  zones = ZONES,
  solvedBy = {} as Record<string, string>,
  challenges = [challenge()],
} = {}) {
  stubFetch((path) => {
    if (path.endsWith("/auth/me")) return { status: 200, body: me() };
    if (path.includes("/progress")) {
      return { status: 200, body: { zones, solved_by: solvedBy } };
    }
    if (path.includes("/challenges")) return { status: 200, body: challenges };
    return { status: 200, body: {} };
  });
  renderApp(<PartyCoverage teamId="t1" />);
}

describe("PartyCoverage", () => {
  it("shows each zone's share, counted for the party rather than the player", async () => {
    render();

    expect(await screen.findByText("1/2")).toBeInTheDocument();
    expect(screen.getByText("0/6")).toBeInTheDocument();
  });

  it("says the union rule out loud, because it is the whole point", async () => {
    render();

    // Two members on one challenge is wasted effort, and nothing said so before.
    expect(
      await screen.findByText(/A challenge counts once, however many of you solve it/),
    ).toBeInTheDocument();
  });

  it("marks a sealed zone without hiding that it exists", async () => {
    render();

    const row = (await screen.findByText("The Vaults")).closest("button")!;
    expect(within(row).getByLabelText("Sealed")).toBeInTheDocument();
    // Knowing there is more is the point.
    expect(within(row).getByText("0/6")).toBeInTheDocument();
  });

  it("names who claimed a challenge when a zone is opened", async () => {
    render({
      solvedBy: { c1: "Rin" },
      challenges: [challenge({ id: "c1", title: "Port of Call" })],
    });

    await userEvent.click(await screen.findByText("Networking"));

    // "Rin has this one; it will not pay twice."
    expect(screen.getByText("Rin")).toBeInTheDocument();
  });

  it("leaves an unclaimed challenge unnamed", async () => {
    render({
      solvedBy: {},
      challenges: [challenge({ id: "c1", title: "Port of Call" })],
    });
    await userEvent.click(await screen.findByText("Networking"));

    const row = screen.getByText("Port of Call").closest("li")!;
    expect(within(row).getByText("○")).toBeInTheDocument();
  });

  it("does not name a sealed challenge it cannot name", async () => {
    render({
      challenges: [challenge({ id: "c1", title: null, slug: null, locked: true })],
    });

    await userEvent.click(await screen.findByText("Networking"));

    // The server withholds a sealed title (spec 062 §4.2), so there is nothing
    // to render but the fact of it.
    expect(screen.getByText("Sealed")).toBeInTheDocument();
  });

  it("collapses again", async () => {
    render({ challenges: [challenge({ id: "c1", title: "Port of Call" })] });
    await userEvent.click(await screen.findByText("Networking"));
    expect(screen.getByText("Port of Call")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Networking"));

    expect(screen.queryByText("Port of Call")).not.toBeInTheDocument();
  });

  it("says so when nothing is unsealed yet", async () => {
    render({ zones: [] });

    expect(await screen.findByText("Nothing unsealed yet.")).toBeInTheDocument();
  });
});
