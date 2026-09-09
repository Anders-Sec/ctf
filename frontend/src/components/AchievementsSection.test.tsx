import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AchievementsSection from "./AchievementsSection";
import { renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const BODY = {
  earned: 2,
  total: 4,
  items: [
    {
      id: "a1",
      name: "First Blood",
      description: "Solved your first challenge.",
      earned: true,
      rarity: 0.82,
    },
    {
      id: "a2",
      name: "Blitz",
      description: "Three inside five minutes.",
      earned: true,
      rarity: 0.0004,
    },
    { id: "a3", name: null, description: null, earned: false, rarity: null },
    { id: "a4", name: null, description: null, earned: false, rarity: null },
  ],
  rarest: [
    {
      id: "a2",
      name: "Blitz",
      description: "Three inside five minutes.",
      earned: true,
      rarity: 0.0004,
    },
  ],
};

function render(body: unknown = BODY) {
  stubFetch((path) => {
    if (path.endsWith("/character/achievements")) return { status: 200, body };
    return { status: 200, body: {} };
  });
  renderApp(<AchievementsSection />);
}

describe("AchievementsSection", () => {
  it("shows how many are earned out of the public total", async () => {
    render();

    // The total is public on purpose — it is something to aim at.
    expect(await screen.findByText("2 of 4 earned")).toBeInTheDocument();
  });

  it("names earned achievements and leaves unearned ones unnamed", async () => {
    render();

    expect(await screen.findByText("First Blood")).toBeInTheDocument();
    // The server sends no name for an unearned one, so there is nothing here
    // to un-blur in devtools.
    expect(screen.getAllByText("Undiscovered achievement")).toHaveLength(4);
  });

  it("shows the rarest held with a percentage", async () => {
    render();

    expect(await screen.findByText("Rarest held")).toBeInTheDocument();
    expect(screen.getByText("<0.1% of players")).toBeInTheDocument();
  });

  it("does not round a very rare achievement down to zero", async () => {
    render();

    // 0.04% must not read as "0% of players" when the viewer is holding it.
    expect(await screen.findByText("<0.1% of players")).toBeInTheDocument();
    expect(screen.queryByText("0% of players")).not.toBeInTheDocument();
  });

  it("stays out of the way when there are no achievements at all", () => {
    render({ earned: 0, total: 0, items: [], rarest: [] });

    expect(screen.queryByText("Achievements")).not.toBeInTheDocument();
  });

  it("survives a partial response rather than taking the sheet down", () => {
    render({});

    expect(screen.queryByText("Achievements")).not.toBeInTheDocument();
  });
});
