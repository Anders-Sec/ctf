import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import DungeonMap from "./DungeonMap";
import type { DungeonMap as MapData } from "../api/dungeon";
import { renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function requirement(description: string) {
  return {
    type: "percent_in_category",
    met: false,
    description,
    challenge_id: null,
    title: null,
    skill_id: null,
    skill_name: null,
    category_id: null,
    category_name: null,
    threshold: 50,
    progress: 10,
  };
}

const DATA: MapData = {
  fog_of_war: true,
  zones: [
    {
      id: "z1",
      name: "Intro",
      slug: "intro",
      ability: "int",
      display_order: 0,
      x: 0,
      y: 0,
      locked: false,
      unlock_requirements: [],
      cleared: 1,
      total: 1,
    },
    {
      id: "z2",
      name: "Networking",
      slug: "networking",
      ability: "int",
      display_order: 1,
      x: 0,
      y: 1,
      locked: true,
      unlock_requirements: [requirement("Clear 100% of Intro")],
      cleared: 0,
      total: 4,
    },
  ],
  edges: [{ from_zone_id: "z1", to_zone_id: "z2" }],
};

describe("DungeonMap", () => {
  it("draws a node per zone, labelled with its state", () => {
    renderApp(<DungeonMap data={DATA} />);

    expect(screen.getByLabelText("Intro — open, 1 of 1 cleared")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Networking — sealed, needs Clear 100% of Intro"),
    ).toBeInTheDocument();
  });

  it("keeps a sealed zone readable and states what opens it", () => {
    renderApp(<DungeonMap data={DATA} />);

    // Greyed, not hidden: the zone, its progress and its condition all show.
    expect(screen.getByText("Networking")).toBeInTheDocument();
    expect(screen.getByText("0/4 cleared")).toBeInTheDocument();
    expect(screen.getByText("Clear 100% of Intro")).toBeInTheDocument();
  });

  it("opens a panel of that zone's challenges", async () => {
    stubFetch((path) => {
      if (path.endsWith("/challenges")) {
        return {
          status: 200,
          body: [
            {
              id: "c1",
              title: "First Steps",
              slug: "first-steps",
              category: { id: "z1", name: "Intro", slug: "intro", description: null, display_order: 0 },
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
            },
          ],
        };
      }
      return { status: 200, body: [] };
    });

    renderApp(<DungeonMap data={DATA} />);
    await userEvent.click(screen.getByLabelText("Intro — open, 1 of 1 cleared"));

    const panel = await screen.findByRole("dialog", { name: "Intro challenges" });
    expect(await within(panel).findByText("First Steps")).toBeInTheDocument();
  });

  it("closes the panel on Escape", async () => {
    stubFetch(() => ({ status: 200, body: [] }));

    renderApp(<DungeonMap data={DATA} />);
    await userEvent.click(screen.getByLabelText("Intro — open, 1 of 1 cleared"));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("says so when there is nothing to draw", () => {
    renderApp(<DungeonMap data={{ ...DATA, zones: [], edges: [] }} />);

    expect(screen.getByText(/dungeon is empty/i)).toBeInTheDocument();
  });
});
