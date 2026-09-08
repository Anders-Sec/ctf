import { screen, waitFor } from "@testing-library/react";
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

describe("CharacterSheetPage", () => {
  it("shows the player's own level, total XP and skills", async () => {
    stubFetch((path) => {
      if (path.endsWith("/auth/me")) return { status: 200, body: me() };
      if (path.endsWith("/character/me")) return { status: 200, body: OWN_SHEET };
      if (path.endsWith("/character/classes")) return { status: 200, body: [] };
      return { status: 200, body: {} };
    });

    renderApp(<CharacterSheetPage />, { route: "/character" });

    expect(await screen.findByText("600 XP total")).toBeInTheDocument();
    expect(screen.getByText("Injection Artistry")).toBeInTheDocument();
    expect(screen.getByText(/rank #2/)).toBeInTheDocument();
    // The stat block shows scores, and never a progress figure.
    expect(screen.getByText("Strength")).toBeInTheDocument();
    expect(screen.getByText("14")).toBeInTheDocument();
  });

  it("hides funny skills when asked, and blurs undiscovered ones", async () => {
    stubFetch((path) => {
      if (path.endsWith("/auth/me")) return { status: 200, body: me() };
      if (path.endsWith("/character/me")) return { status: 200, body: OWN_SHEET };
      if (path.endsWith("/character/classes")) return { status: 200, body: [] };
      return { status: 200, body: {} };
    });

    renderApp(<CharacterSheetPage />, { route: "/character" });

    // Undiscovered rows are present but carry only the server's placeholder —
    // the real name never reached the browser.
    expect(await screen.findByText("2 of 3 discovered")).toBeInTheDocument();
    expect(screen.getByLabelText("Undiscovered skill")).toBeInTheDocument();

    expect(screen.getByText("Magic Smoke Attraction")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Hide funny skills"));
    expect(screen.queryByText("Magic Smoke Attraction")).not.toBeInTheDocument();
  });

  it("sets the player's class from the picker", async () => {
    const fetchMock = stubFetch((path, init) => {
      if (path.endsWith("/auth/me")) return { status: 200, body: me() };
      if (path.endsWith("/character/class") && init?.method === "PUT") {
        return {
          status: 200,
          body: {
            ...OWN_SHEET,
            character_class: {
              id: "cl1",
              name: "Rogue",
              description: null,
              rarity: "common",
            },
          },
        };
      }
      if (path.endsWith("/character/me")) return { status: 200, body: OWN_SHEET };
      if (path.endsWith("/character/classes")) {
        return { status: 200, body: [{ id: "cl1", name: "Rogue", description: null }] };
      }
      return { status: 200, body: {} };
    });

    renderApp(<CharacterSheetPage />, { route: "/character" });

    // Wait for the roster to load (the select is disabled until it does).
    await screen.findByRole("option", { name: "Rogue" });
    const select = screen.getByLabelText("Class");
    await userEvent.selectOptions(select, "cl1");

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).endsWith("/character/class") && init?.method === "PUT",
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ class_id: "cl1" });
    });
  });

  it("locks the picker below the unlock level", async () => {
    stubFetch((path) => {
      if (path.endsWith("/auth/me")) return { status: 200, body: me() };
      if (path.endsWith("/character/me")) return { status: 200, body: LOCKED_SHEET };
      return { status: 200, body: {} };
    });

    renderApp(<CharacterSheetPage />, { route: "/character" });

    expect(await screen.findByText(/Reach level 5 to choose a class/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Class")).not.toBeInTheDocument();
  });

  it("shows another player's public sheet with class and no rank", async () => {
    stubFetch((path) => {
      if (path.endsWith("/auth/me")) return { status: 200, body: me() };
      if (path.includes("/character/22222222")) {
        return { status: 200, body: PUBLIC_SHEET };
      }
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
    expect(screen.queryByLabelText("Class")).not.toBeInTheDocument();
  });
});


describe("class rarity and the System AI nudge (spec 024)", () => {
  function render(overrides: Record<string, unknown>, roster: unknown[] = []) {
    stubFetch((path) => {
      if (path.endsWith("/auth/me")) return { status: 200, body: me() };
      if (path.endsWith("/character/me"))
        return { status: 200, body: { ...OWN_SHEET, ...overrides } };
      if (path.endsWith("/character/classes")) return { status: 200, body: roster };
      return { status: 200, body: {} };
    });
    renderApp(<CharacterSheetPage />, { route: "/character" });
  }

  it("names the rarity as text, not only as colour", async () => {
    render({
      character_class: {
        id: "cl9",
        name: "Cryptomancer",
        description: null,
        rarity: "mythic",
      },
    });

    // Colour is never the only signal: this has to survive greyscale and reach
    // a screen reader.
    expect(await screen.findByText("mythic")).toBeInTheDocument();
  });

  it("shows the System AI's nudge when there is one", async () => {
    render({
      suggested_class: { id: "cl2", name: "Analyst", description: null, rarity: "common" },
      suggested_class_line:
        "You keep hammering Log Divination problems. The Analyst build fits the pattern — take it or don't.",
    });

    expect(await screen.findByText(/the Analyst build fits/i)).toBeInTheDocument();
  });

  it("says nothing when there is no suggestion", async () => {
    render({});

    expect(await screen.findByRole("combobox", { name: "Class" })).toBeInTheDocument();
    expect(screen.queryByText(/fits the pattern/i)).not.toBeInTheDocument();
  });

  it("offers only the classes the server sent", async () => {
    render({}, [
      { id: "cl1", name: "Rogue", description: null, rarity: "common" },
      { id: "cl2", name: "Packet Sage", description: null, rarity: "uncommon" },
    ]);

    // Locked classes never reach the client at all — the roster is a mystery,
    // so there is nothing here to reveal one exists.
    const picker = await screen.findByRole("combobox", { name: "Class" });
    expect([...picker.querySelectorAll("option")].map((o) => o.textContent)).toEqual([
      "Classless",
      "Rogue",
      "Packet Sage",
    ]);
  });
});
