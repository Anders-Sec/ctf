import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DungeonMap from "./DungeonMap";
import type { DungeonMap as MapData } from "../api/dungeon";
import { renderApp } from "../test/utils";

function requirement(description: string) {
  return {
    type: "min_xp",
    met: false,
    description,
    challenge_id: null,
    title: null,
    skill_id: null,
    skill_name: null,
    category_id: null,
    category_name: null,
    threshold: 600,
    progress: 0,
  };
}

const DATA: MapData = {
  fog_of_war: true,
  zones: [
    {
      id: "z1",
      name: "Warm-Up",
      display_order: 1,
      locked: false,
      unlock_requirements: [],
      cleared: 1,
      total: 2,
    },
    {
      id: "z2",
      name: "Deep Wing",
      display_order: 2,
      locked: true,
      unlock_requirements: [requirement("Reach 600 XP")],
      cleared: 0,
      total: 1,
    },
  ],
  rooms: [
    {
      challenge_id: "c1",
      title: "First Steps",
      zone_id: "z1",
      x: 0,
      y: 0,
      state: "cleared",
      value: 100,
      solved: true,
      unlock_requirements: [],
    },
    {
      challenge_id: "c2",
      title: "Second Steps",
      zone_id: "z1",
      x: 0,
      y: 1,
      state: "shut",
      value: 200,
      solved: false,
      unlock_requirements: [
        { ...requirement("Solve First Steps"), type: "challenge_solved" },
      ],
    },
    {
      challenge_id: "c3",
      title: "Inner Sanctum",
      zone_id: "z2",
      x: 0,
      y: 0,
      state: "shut",
      value: 500,
      solved: false,
      unlock_requirements: [],
    },
  ],
  edges: [{ from_challenge_id: "c1", to_challenge_id: "c2" }],
};

describe("DungeonMap", () => {
  it("draws a room per challenge, labelled with its state", () => {
    renderApp(<DungeonMap data={DATA} />);

    expect(screen.getByLabelText("First Steps — cleared")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Second Steps — shut, needs Solve First Steps"),
    ).toBeInTheDocument();
  });

  it("shows each zone with its progress", () => {
    renderApp(<DungeonMap data={DATA} />);

    expect(screen.getByText("Warm-Up")).toBeInTheDocument();
    expect(screen.getByText(/1\/2/)).toBeInTheDocument();
  });

  it("keeps a locked zone readable and states what opens it", () => {
    renderApp(<DungeonMap data={DATA} />);

    // Greyed, not hidden: the wing, its room and its condition are all present.
    expect(screen.getByText("Deep Wing")).toBeInTheDocument();
    expect(screen.getByLabelText("Inner Sanctum — shut")).toBeInTheDocument();
    expect(screen.getByText("Reach 600 XP")).toBeInTheDocument();
  });

  it("marks rooms behind a lock as not enterable", () => {
    renderApp(<DungeonMap data={DATA} />);

    expect(screen.getByLabelText("First Steps — cleared")).toHaveAttribute(
      "aria-disabled",
      "false",
    );
    expect(screen.getByLabelText("Inner Sanctum — shut")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("says so when there is nothing to draw", () => {
    renderApp(<DungeonMap data={{ ...DATA, rooms: [], zones: [], edges: [] }} />);

    expect(screen.getByText(/dungeon is empty/i)).toBeInTheDocument();
  });
});
