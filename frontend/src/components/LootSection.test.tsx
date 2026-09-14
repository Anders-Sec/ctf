import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import LootSection from "./LootSection";
import { renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const BOXES = [
  {
    id: "b1",
    box_type: "cartographer",
    rarity: "celestial",
    achievement_name: "The Whole Dungeon",
    created_at: "2026-09-14T10:00:00Z",
  },
];

const TITLES = [
  {
    item_id: "i1",
    title: "Owner Of The Map",
    rarity: "platinum",
    box_type: "cartographer",
    generated: false,
    equipped: false,
  },
  {
    item_id: "i2",
    title: "Line Item",
    rarity: "bronze",
    box_type: "adventurer",
    generated: false,
    equipped: true,
  },
];

function render({ boxes = BOXES, titles = TITLES, opened = null as unknown } = {}) {
  const mock = stubFetch((path) => {
    if (path.endsWith("/loot/boxes")) return { status: 200, body: boxes };
    if (path.endsWith("/loot/titles")) return { status: 200, body: titles };
    if (path.includes("/loot/boxes/") && path.endsWith("/open")) {
      return { status: 200, body: opened ?? {} };
    }
    if (path.endsWith("/loot/equipped")) return { status: 200, body: { message: "ok" } };
    return { status: 200, body: {} };
  });
  renderApp(<LootSection />);
  return mock;
}

describe("LootSection", () => {
  it("lists unopened boxes with what dropped them", async () => {
    render();

    expect(await screen.findByText("celestial Cartographer Box")).toBeInTheDocument();
    expect(screen.getByText("The Whole Dungeon")).toBeInTheDocument();
  });

  it("opens a box and reveals the title", async () => {
    const fetchMock = render({
      opened: {
        box_id: "b1",
        title: "Every Wing. Every Room.",
        rarity: "celestial",
        box_type: "cartographer",
        generated: false,
      },
    });

    await userEvent.click(await screen.findByRole("button", { name: "Open" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).includes("/loot/boxes/b1/open") && init?.method === "POST",
      );
      expect(call).toBeDefined();
    });
    expect(await screen.findByText("Every Wing. Every Room.")).toBeInTheDocument();
  });

  it("marks a title the model wrote for this player", async () => {
    render({
      opened: {
        box_id: "b1",
        title: "The Last Door, Personally",
        rarity: "celestial",
        box_type: "cartographer",
        generated: true,
      },
    });

    await userEvent.click(await screen.findByRole("button", { name: "Open" }));

    expect(await screen.findByText(/written for you, just now/i)).toBeInTheDocument();
  });

  it("wears a title, and takes off the one already on", async () => {
    const fetchMock = render();
    await screen.findByText("Owner Of The Map");

    await userEvent.click(screen.getByRole("button", { name: "Wear" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).endsWith("/loot/equipped") && init?.method === "PUT",
      );
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ item_id: "i1" });
    });

    // The equipped one offers removal instead.
    expect(screen.getByRole("button", { name: "Take off" })).toBeInTheDocument();
  });

  it("takes a worn title off by sending null", async () => {
    const fetchMock = render();
    await screen.findByText("Line Item");

    await userEvent.click(screen.getByRole("button", { name: "Take off" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).endsWith("/loot/equipped") && init?.method === "PUT",
      );
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ item_id: null });
    });
  });

  it("says nothing at all when there is no loot", () => {
    render({ boxes: [], titles: [] });

    expect(screen.queryByText("Loot")).not.toBeInTheDocument();
  });

  it("survives a partial response rather than taking the sheet down", () => {
    render({ boxes: {} as never, titles: {} as never });

    expect(screen.queryByText("Loot")).not.toBeInTheDocument();
  });

  it("explains that a worn title shows on the board", async () => {
    render();

    // The reason a cosmetic title is worth anything at all.
    expect(
      await screen.findByText(/shows beside your name on the scoreboard/i),
    ).toBeInTheDocument();
  });
});
