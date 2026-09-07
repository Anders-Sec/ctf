import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

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

describe("ChallengesPage", () => {
  it("shows a challenge with its current value", async () => {
    withBoard([challenge()]);

    expect(await screen.findByText("Packet Puzzle")).toBeInTheDocument();
    expect(screen.getByText("420")).toBeInTheDocument();
  });

  it("shows the player's running total", async () => {
    withBoard([challenge()], 1250);

    expect(await screen.findByLabelText("Your score")).toHaveTextContent("1250");
  });

  it("marks solved challenges", async () => {
    withBoard([challenge({ solved: true })]);

    // Specific: the "Hide solved" filter label also contains the word.
    expect(await screen.findByText("✓ solved")).toBeInTheDocument();
  });

  it("shows a locked challenge but does not link to it", async () => {
    // There is nothing behind it yet, and the server would refuse anyway.
    withBoard([challenge({ locked: true, title: "Sealed Vault" })]);

    expect(await screen.findByText("Sealed Vault")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Sealed Vault/ })).not.toBeInTheDocument();
  });

  it("links to an open challenge", async () => {
    withBoard([challenge()]);

    const link = await screen.findByRole("link", { name: /Packet Puzzle/ });
    expect(link).toHaveAttribute("href", "/challenges/c1");
  });

  it("groups challenges by category", async () => {
    withBoard([
      challenge({ id: "a", title: "Web One" , category: { id: "w", name: "Web", slug: "web", description: null, display_order: 0 }}),
      challenge({ id: "b", title: "Forensics One" }),
    ]);

    const web = (await screen.findByRole("heading", { name: "Web" })).parentElement!;
    expect(within(web).getByText("Web One")).toBeInTheDocument();
    expect(within(web).queryByText("Forensics One")).not.toBeInTheDocument();
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

    expect(await screen.findByText(/2 of 3 attempts left/i)).toBeInTheDocument();
  });

  it("says so when nothing is available yet", async () => {
    withBoard([]);

    expect(await screen.findByText(/nothing has been unsealed/i)).toBeInTheDocument();
  });
});
