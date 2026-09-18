import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import CharacterSheetPage from "./CharacterSheetPage";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const OWN_SHEET = {
  user_id: "11111111-1111-1111-1111-111111111111",
  display_name: "Grix",
  has_avatar: false,
  total_xp: 600,
  level: 3,
  xp_into_level: 0,
  xp_to_next: 600,
  rank: 2,
  abilities: [
    { ability: "str", score: 14 },
    { ability: "dex", score: 8 },
    { ability: "con", score: 8 },
    { ability: "int", score: 12 },
    { ability: "wis", score: 8 },
    { ability: "cha", score: 8 },
  ],
  skills: [
    { skill_id: "s1", name: "Injection Artistry", kind: "useful", level: 3, discovered: true },
    { skill_id: "s2", name: "Magic Smoke Attraction", kind: "funny", level: 1, discovered: true },
    { skill_id: "s3", name: "Undiscovered skill", kind: "useful", level: 0, discovered: false },
  ],
  character_class: null,
  class_unlocked: true,
  class_unlock_level: 5,
  suggested_class: null,
  suggested_class_line: null,
  party: null,
  equipped_title: null,
};

const LOCKED_SHEET = {
  ...OWN_SHEET,
  level: 1,
  total_xp: 0,
  class_unlocked: false,
};

const PUBLIC_SHEET = {
  user_id: "22222222-2222-2222-2222-222222222222",
  display_name: "Sir Solves",
  has_avatar: false,
  level: 2,
  abilities: [{ ability: "str", score: 10 }],
  skills: [
    { skill_id: "s1", name: "Injection Artistry", kind: "useful", level: 2, discovered: true },
  ],
  character_class: { id: "cl1", name: "Rogue", description: null, rarity: "common" },
};

const NO_ACHIEVEMENTS = { earned: 0, total: 0, items: [], rarest: [] };

function render({
  sheet = {},
  roster = [] as unknown[],
  achievements = NO_ACHIEVEMENTS as unknown,
  boxes = [] as unknown[],
  titles = [] as unknown[],
} = {}) {
  const mock = stubFetch((path, init) => {
    if (path.endsWith("/auth/me")) return { status: 200, body: me() };
    if (path.endsWith("/character/class") && init?.method === "PUT") {
      return { status: 200, body: { ...OWN_SHEET, ...sheet, ...JSON.parse(String(init.body)) } };
    }
    if (path.endsWith("/character/me")) return { status: 200, body: { ...OWN_SHEET, ...sheet } };
    if (path.endsWith("/character/classes")) return { status: 200, body: roster };
    if (path.endsWith("/character/achievements")) return { status: 200, body: achievements };
    if (path.endsWith("/loot/boxes")) return { status: 200, body: boxes };
    if (path.endsWith("/loot/titles")) return { status: 200, body: titles };
    if (path.includes("/loot/boxes/") && init?.method === "POST") {
      return {
        status: 200,
        body: {
          box_id: "b1",
          title: "the Unbothered",
          rarity: "gold",
          box_type: "adventurer",
          generated: false,
        },
      };
    }
    return { status: 200, body: {} };
  });
  renderApp(<CharacterSheetPage />, { route: "/character" });
  return mock;
}

describe("the player info block", () => {
  it("collapses identity into one block: name, class, level, rank and party", async () => {
    render({ sheet: { party: { id: "t1", name: "The Mimics" } } });

    expect(await screen.findByText("Grix")).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "The Mimics" })).toHaveAttribute("href", "/party");
    // Level is named once now. It used to appear in the header and again in a
    // section two blocks below it.
    expect(screen.getAllByText("Level")).toHaveLength(1);
  });

  it("shows the worn title beside the name", async () => {
    render({ sheet: { equipped_title: "the Unbothered" } });

    // The name plate everybody else sees on the board; before spec 060 its owner
    // could only find it inside the loot inventory.
    expect(await screen.findByText("the Unbothered")).toBeInTheDocument();
  });

  it("shows XP as numbers, not only a bar", async () => {
    render({ sheet: { total_xp: 600, xp_into_level: 150, xp_to_next: 450 } });

    // The one screen the XP rule allows (spec 059 §2), so it is not coy about it.
    expect(await screen.findByText("600 XP total")).toBeInTheDocument();
    expect(screen.getByText("150 / 600 XP to level 4")).toBeInTheDocument();
  });

  it("says so at the top of the curve rather than showing a broken bar", async () => {
    render({ sheet: { xp_to_next: 0 } });

    expect(await screen.findByText("Top of the curve for now")).toBeInTheDocument();
  });

  it("reads as unranked rather than blank before the first solve", async () => {
    render({ sheet: { rank: null } });

    expect(await screen.findByText("unranked")).toBeInTheDocument();
  });
});

describe("choosing a class", () => {
  it("opens from the class name and sets one", async () => {
    const fetchMock = render({
      roster: [{ id: "cl1", name: "Rogue", description: null, rarity: "common" }],
    });

    await userEvent.click(await screen.findByRole("button", { name: "Classless" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose a class" });
    await userEvent.click(within(dialog).getByRole("button", { name: /Rogue/ }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) => String(path).endsWith("/character/class") && init?.method === "PUT",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ class_id: "cl1" });
    });
    // It closes on success rather than leaving the player to dismiss it.
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Choose a class" })).not.toBeInTheDocument(),
    );
  });

  it("offers only the classes the server sent", async () => {
    render({
      roster: [
        { id: "cl1", name: "Rogue", description: null, rarity: "common" },
        { id: "cl2", name: "Packet Sage", description: null, rarity: "uncommon" },
      ],
    });

    await userEvent.click(await screen.findByRole("button", { name: "Classless" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose a class" });

    // Locked classes never reach the client at all — the roster is a mystery, so
    // there is nothing here to reveal one exists.
    const names = within(dialog)
      .getAllByRole("button")
      .map((button) => button.textContent ?? "")
      .filter((text) => text !== "×");
    expect(names[0]).toContain("Classless");
    expect(names[1]).toContain("Rogue");
    expect(names[2]).toContain("Packet Sage");
    expect(names).toHaveLength(3);
  });

  it("shows the gate instead of a roster below the unlock level", async () => {
    render({ sheet: LOCKED_SHEET });

    await userEvent.click(await screen.findByRole("button", { name: "Classless" }));

    expect(await screen.findByText(/Reach level 5 to choose a class/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Rogue/ })).not.toBeInTheDocument();
  });

  it("names the class rarity as text, not only as colour", async () => {
    render({
      sheet: {
        character_class: { id: "cl9", name: "Cryptomancer", description: null, rarity: "mythic" },
      },
      roster: [{ id: "cl9", name: "Cryptomancer", description: null, rarity: "mythic" }],
    });

    await userEvent.click(await screen.findByRole("button", { name: "Cryptomancer" }));

    // Colour is never the only signal: it has to survive greyscale and reach a
    // screen reader.
    expect(await screen.findByText("mythic")).toBeInTheDocument();
  });

  it("carries the System AI's nudge when there is one", async () => {
    render({
      sheet: {
        suggested_class: { id: "cl2", name: "Analyst", description: null, rarity: "common" },
        suggested_class_line:
          "You keep hammering Log Divination problems. The Analyst build fits the pattern.",
      },
    });

    await userEvent.click(await screen.findByRole("button", { name: "Classless" }));

    expect(await screen.findByText(/the Analyst build fits/i)).toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    render();
    await userEvent.click(await screen.findByRole("button", { name: "Classless" }));
    await screen.findByRole("dialog", { name: "Choose a class" });

    await userEvent.keyboard("{Escape}");

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Choose a class" })).not.toBeInTheDocument(),
    );
  });
});

describe("the stats panel", () => {
  it("shows the six ability scores and never their progress", async () => {
    render();

    expect(await screen.findByText("STR")).toBeInTheDocument();
    expect(screen.getByText("14")).toBeInTheDocument();
    expect(screen.getByText("2 of 3 skills discovered")).toBeInTheDocument();
  });

  it("blurs an undiscovered skill, and cannot find it by name", async () => {
    render();
    await screen.findByText("Injection Artistry");

    // The real name never reached the browser — the blur is honest rather than
    // cosmetic.
    expect(screen.getByLabelText("Undiscovered skill")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Search skills"), "Undiscovered");
    expect(screen.queryByLabelText("Undiscovered skill")).not.toBeInTheDocument();
  });

  it("filters by kind", async () => {
    render();
    await screen.findByText("Magic Smoke Attraction");

    await userEvent.selectOptions(screen.getByLabelText("Any kind"), "useful");

    expect(screen.queryByText("Magic Smoke Attraction")).not.toBeInTheDocument();
    expect(screen.getByText("Injection Artistry")).toBeInTheDocument();
  });

  it("filters to discovered skills only", async () => {
    render();
    await screen.findByText("Injection Artistry");

    await userEvent.selectOptions(screen.getByLabelText("All skills"), "yes");

    expect(screen.queryByLabelText("Undiscovered skill")).not.toBeInTheDocument();
    expect(screen.getByText("Injection Artistry")).toBeInTheDocument();
  });

  it("searches by name", async () => {
    render();
    await screen.findByText("Injection Artistry");

    await userEvent.type(screen.getByLabelText("Search skills"), "smoke");

    expect(screen.getByText("Magic Smoke Attraction")).toBeInTheDocument();
    expect(screen.queryByText("Injection Artistry")).not.toBeInTheDocument();
  });
});

describe("the achievements panel", () => {
  const ROSTER = {
    earned: 2,
    total: 4,
    items: [
      { id: "a1", name: "First Blood", description: "You drew it first.", earned: true, rarity: 0.021 },
      { id: "a2", name: "Night Owl", description: "Late.", earned: true, rarity: 0.14 },
      { id: "a3", name: null, description: null, earned: false, rarity: null },
      { id: "a4", name: null, description: null, earned: false, rarity: null },
    ],
    rarest: [
      { id: "a1", name: "First Blood", description: "You drew it first.", earned: true, rarity: 0.021 },
      { id: "a2", name: "Night Owl", description: "Late.", earned: true, rarity: 0.14 },
    ],
  };

  it("shows the rarest held with their percentages", async () => {
    render({ achievements: ROSTER });

    expect(await screen.findByText("2 of 4 earned")).toBeInTheDocument();
    expect(screen.getAllByText("First Blood").length).toBeGreaterThan(0);
    expect(screen.getAllByText("2.1%").length).toBeGreaterThan(0);
  });

  it("keeps five slots whether or not they are filled", async () => {
    render({ achievements: ROSTER });
    await screen.findByText("2 of 4 earned");

    // The row must not change size as a player's rarest five change (§2.1).
    expect(screen.getAllByText("An empty slot for a rare achievement")).toHaveLength(3);
  });

  it("cannot find an unearned achievement by name", async () => {
    render({ achievements: ROSTER });
    await screen.findByText("2 of 4 earned");
    expect(screen.getAllByText("Undiscovered achievement").length).toBeGreaterThan(0);

    // Spec 028 redacts the name server-side, so there is genuinely nothing to
    // search — and the panel says so rather than leaving it a mystery.
    expect(
      screen.getByText("Only achievements you have earned can be found by name."),
    ).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Search achievements"), "First");
    expect(screen.queryByText("Undiscovered achievement")).not.toBeInTheDocument();
  });

  it("filters to the ones not yet earned", async () => {
    render({ achievements: ROSTER });
    await screen.findByText("2 of 4 earned");

    await userEvent.selectOptions(screen.getByLabelText("All"), "no");

    // Scoped to the list: the rarest-five cards above it are a separate display
    // and the filter deliberately does not touch them.
    const list = screen.getByRole("list", { name: "Achievements" });
    expect(within(list).queryByText("First Blood")).not.toBeInTheDocument();
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
  });

  it("says what is coming rather than apologising when there are none", async () => {
    render();

    // Day one is a glass half full: four full-height panels showing everything
    // there is to unlock (§9.2).
    expect(
      await screen.findByText("None yet. There are plenty waiting to be found."),
    ).toBeInTheDocument();
  });
});

describe("the loot panel", () => {
  const BOXES = [
    {
      id: "b1",
      box_type: "adventurer",
      rarity: "bronze",
      achievement_name: "First Blood",
      created_at: "2026-09-01T00:00:00Z",
    },
    {
      id: "b2",
      box_type: "boss",
      rarity: "celestial",
      achievement_name: "The Floor",
      created_at: "2026-09-02T00:00:00Z",
    },
  ];
  const TITLES = [
    {
      item_id: "i1",
      title: "the Unbothered",
      rarity: "gold",
      box_type: "adventurer",
      generated: false,
      equipped: true,
    },
    {
      item_id: "i2",
      title: "the Persistent",
      rarity: "bronze",
      box_type: "boss",
      generated: false,
      equipped: false,
    },
  ];

  it("orders the shelf by rarity, best first", async () => {
    render({ boxes: BOXES });

    const shelf = await screen.findByRole("group", { name: "Unopened loot boxes" });
    const labels = within(shelf)
      .getAllByRole("button")
      .map((button) => button.textContent ?? "");
    expect(labels[0]).toContain("celestial");
    expect(labels[1]).toContain("bronze");
  });

  it("keeps the shelf at one height with nothing on it", async () => {
    render();

    const shelf = await screen.findByRole("group", { name: "Unopened loot boxes" });
    // It says so rather than collapsing, so opening the last box does not move
    // the page under the player mid-ceremony.
    expect(within(shelf).getByText(/Nothing to open/)).toBeInTheDocument();
    expect(shelf.className).toContain("h-20");
  });

  it("opens a box and reveals what was inside", async () => {
    render({ boxes: BOXES });
    const shelf = await screen.findByRole("group", { name: "Unopened loot boxes" });

    await userEvent.click(within(shelf).getAllByRole("button")[0]!);

    expect(await screen.findByRole("status")).toHaveTextContent("the Unbothered");
  });

  it("marks the worn title and offers to take it off", async () => {
    render({ titles: TITLES });

    await screen.findByText("the Unbothered");
    expect(screen.getByText("worn")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Take off" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wear" })).toBeInTheDocument();
  });

  it("filters titles by rarity", async () => {
    render({ titles: TITLES });
    await screen.findByText("the Unbothered");

    await userEvent.selectOptions(screen.getByLabelText("Any rarity"), "gold");

    expect(screen.getByText("the Unbothered")).toBeInTheDocument();
    expect(screen.queryByText("the Persistent")).not.toBeInTheDocument();
  });
});

describe("what left the sheet", () => {
  it("no longer shows bosses felled", async () => {
    const fetchMock = render();
    await screen.findByText("Grix");

    // A player can see which bosses they have beaten on the challenge list, and
    // the stars are on both scoreboards (spec 059).
    expect(screen.queryByText(/bosses felled/i)).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([path]) => String(path).endsWith("/character/stars")),
    ).toBe(false);
  });
});

describe("somebody else's sheet", () => {
  it("is untouched by spec 060", async () => {
    stubFetch((path) => {
      if (path.endsWith("/auth/me")) return { status: 200, body: me() };
      if (path.includes("/character/22222222")) return { status: 200, body: PUBLIC_SHEET };
      return { status: 200, body: {} };
    });

    renderApp(
      <Routes>
        <Route path="/character/:userId" element={<CharacterSheetPage />} />
      </Routes>,
      { route: "/character/22222222-2222-2222-2222-222222222222" },
    );

    expect(await screen.findByText("Sir Solves")).toBeInTheDocument();
    expect(screen.getByText(/Level 2 Rogue adventurer/)).toBeInTheDocument();
    expect(screen.queryByText(/rank #/)).not.toBeInTheDocument();
    // No class chooser, no loot, no achievements — that pass is next.
    expect(screen.queryByRole("button", { name: "Classless" })).not.toBeInTheDocument();
  });
});
