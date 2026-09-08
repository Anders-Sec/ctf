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

  it("falls back to a procedural chamber when a tile is missing", () => {
    // jsdom never fires Image.onload, so nothing is "available" here — which is
    // exactly the partial-art-set case: the zone must still draw and be usable.
    renderApp(<DungeonMap data={DATA} />);

    const node = screen.getByLabelText("Intro — open, 1 of 1 cleared");
    expect(node.querySelector("image")).toBeNull();
    expect(node).toHaveAttribute("tabindex", "0");
  });

  it("zooms without moving the zones under the cursor", async () => {
    renderApp(<DungeonMap data={DATA} />);

    const svg = document.querySelector("svg")!;
    const before = svg.getAttribute("style");
    await userEvent.click(screen.getByLabelText("Zoom in"));

    // The viewport transforms; the zones keep their own coordinates, so a tile
    // never shifts relative to its neighbours.
    expect(svg.getAttribute("style")).not.toEqual(before);
    expect(svg.getAttribute("style")).toContain("scale(");
  });

  it("treats a drag as a pan rather than opening the zone under it", async () => {
    renderApp(<DungeonMap data={DATA} />);
    const node = screen.getByLabelText("Intro — open, 1 of 1 cleared");

    // Press, move well past the click threshold, release.
    await userEvent.pointer([
      { keys: "[MouseLeft>]", target: node, coords: { clientX: 10, clientY: 10 } },
      { target: node, coords: { clientX: 90, clientY: 70 } },
      { keys: "[/MouseLeft]", target: node },
    ]);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("moves a zone in edit mode and saves where it was dropped", async () => {
    const onMove = vi.fn();
    renderApp(<DungeonMap data={DATA} editable onMove={onMove} />);
    const node = screen.getByLabelText("Intro — open, 1 of 1 cleared");

    await userEvent.pointer([
      { keys: "[MouseLeft>]", target: node, coords: { clientX: 10, clientY: 10 } },
      { target: node, coords: { clientX: 50, clientY: 40 } },
      { target: node, coords: { clientX: 90, clientY: 70 } },
      { keys: "[/MouseLeft]", target: node },
    ]);

    // Total travel is 80x60 from where the drag began, snapped to the 8px grid.
    // The intermediate move must not be counted twice.
    expect(onMove).toHaveBeenCalledWith("z1", 80, 64);
  });

  it("opens the gate editor on a click that did not move", async () => {
    const onEditGates = vi.fn();
    const onMove = vi.fn();
    renderApp(
      <DungeonMap
        data={DATA}
        editable
        onMove={onMove}
        onEditGates={onEditGates}
      />,
    );

    await userEvent.click(screen.getByLabelText("Intro — open, 1 of 1 cleared"));

    // A press that went nowhere edits the zone; it does not save a move to the
    // position it already had, nor open the player-facing challenge panel.
    expect(onEditGates).toHaveBeenCalledWith("z1");
    expect(onMove).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("does not open the gate editor for a drag", async () => {
    const onEditGates = vi.fn();
    renderApp(
      <DungeonMap data={DATA} editable onMove={vi.fn()} onEditGates={onEditGates} />,
    );
    const node = screen.getByLabelText("Intro — open, 1 of 1 cleared");

    await userEvent.pointer([
      { keys: "[MouseLeft>]", target: node, coords: { clientX: 10, clientY: 10 } },
      { target: node, coords: { clientX: 90, clientY: 70 } },
      { keys: "[/MouseLeft]", target: node },
    ]);

    expect(onEditGates).not.toHaveBeenCalled();
  });

  it("marks zones nobody can reach, but only for an admin", () => {
    const { unmount } = renderApp(
      <DungeonMap data={DATA} editable unreachable={new Set(["z2"])} />,
    );
    expect(screen.getByText(/unreachable/i)).toBeInTheDocument();
    unmount();

    // A player can do nothing about it, so telling them only confuses.
    renderApp(<DungeonMap data={DATA} unreachable={new Set(["z2"])} />);
    expect(screen.queryByText(/unreachable/i)).not.toBeInTheDocument();
  });

  it("bends each corridor the same way every render", () => {
    // Curves only — the grid pattern is a path too, and a straight one.
    const curves = () =>
      [...document.querySelectorAll("path")]
        .map((path) => path.getAttribute("d") ?? "")
        .filter((d) => d.includes(" Q "));

    const { unmount } = renderApp(<DungeonMap data={DATA} />);
    const first = curves();
    unmount();

    renderApp(<DungeonMap data={DATA} />);
    const second = curves();

    // Derived from the zone ids, not from chance: every player sees the same
    // dungeon, and it does not twitch on reload.
    expect(first).not.toHaveLength(0);
    expect(second).toEqual(first);
  });

  it("fogs sealed zones and leaves open ones clear", () => {
    renderApp(<DungeonMap data={DATA} />);

    const sealed = screen.getByLabelText(
      "Networking — sealed, needs Clear 100% of Intro",
    );
    const open = screen.getByLabelText("Intro — open, 1 of 1 cleared");

    expect(sealed.querySelector(".dungeon-fog")).not.toBeNull();
    expect(open.querySelector(".dungeon-fog")).toBeNull();
  });

  it("keeps the unlock condition readable through the fog", () => {
    renderApp(<DungeonMap data={DATA} />);
    const sealed = screen.getByLabelText(
      "Networking — sealed, needs Clear 100% of Intro",
    );

    // 017 and 019 both hold that fog puts the torches out but never hides what
    // opens a wing, so the fog must come first in paint order.
    const children = [...sealed.children];
    const fog = children.findIndex((child) =>
      child.classList.contains("dungeon-fog"),
    );
    const label = children.findIndex(
      (child) => child.textContent === "Clear 100% of Intro",
    );
    expect(fog).toBeGreaterThanOrEqual(0);
    expect(label).toBeGreaterThan(fog);
  });

  it("lifts the fog entirely when the event setting is off", () => {
    renderApp(<DungeonMap data={{ ...DATA, fog_of_war: false }} />);

    expect(document.querySelector(".dungeon-fog")).toBeNull();
  });

  it("marks sealed zones so only open ones get the warm glow", () => {
    renderApp(<DungeonMap data={DATA} />);

    // The glow is scoped in CSS; what the component owes is the state hook.
    expect(
      screen.getByLabelText("Networking — sealed, needs Clear 100% of Intro"),
    ).toHaveAttribute("data-locked");
    expect(
      screen.getByLabelText("Intro — open, 1 of 1 cleared"),
    ).not.toHaveAttribute("data-locked");
  });

  it("never lets decoration swallow a click meant for a zone", () => {
    renderApp(<DungeonMap data={DATA} />);

    // Fog, motes and overlay art all sit over the tiles; any one of them
    // catching pointer events would make zones unclickable.
    for (const layer of document.querySelectorAll(
      ".dungeon-fog, .dungeon-mote",
    )) {
      const owner = layer.closest("[pointer-events]") ?? layer;
      expect(owner.getAttribute("pointer-events")).toBe("none");
    }
  });

  it("says so when there is nothing to draw", () => {
    renderApp(<DungeonMap data={{ ...DATA, zones: [], edges: [] }} />);

    expect(screen.getByText(/dungeon is empty/i)).toBeInTheDocument();
  });
});
