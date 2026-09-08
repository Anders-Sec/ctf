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
  skills: [
    { skill_id: "s1", name: "Hacking", xp: 600, level: 3, xp_into_level: 0, xp_to_next: 600 },
  ],
  character_class: null,
  suggested_class: {
    class_id: "cl1",
    name: "Rogue",
    from_skill: "Hacking",
    narration: "You keep hammering Hacking problems. The Rogue build fits the pattern — take it or don't.",
  },
  class_unlocked: true,
  class_unlock_level: 3,
};

const LOCKED_SHEET = {
  ...OWN_SHEET,
  level: 1,
  total_xp: 0,
  suggested_class: null,
  class_unlocked: false,
};

const PUBLIC_SHEET = {
  user_id: "22222222-2222-2222-2222-222222222222",
  display_name: "Sir Solves",
  has_avatar: false,
  level: 2,
  skills: [{ skill_id: "s1", name: "Hacking", level: 2 }],
  character_class: { id: "cl1", name: "Rogue", description: null },
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
    expect(screen.getByText("Hacking")).toBeInTheDocument();
    expect(screen.getByText(/rank #2/)).toBeInTheDocument();
  });

  it("shows the System AI's suggested-class nudge, attributed to it", async () => {
    stubFetch((path) => {
      if (path.endsWith("/auth/me")) return { status: 200, body: me() };
      if (path.endsWith("/character/me")) return { status: 200, body: OWN_SHEET };
      if (path.endsWith("/character/classes")) {
        return { status: 200, body: [{ id: "cl1", name: "Rogue", description: null }] };
      }
      return { status: 200, body: {} };
    });

    renderApp(<CharacterSheetPage />, { route: "/character" });

    const nudge = await screen.findByLabelText("System AI");
    expect(nudge).toHaveTextContent(/The Rogue build fits the pattern/);
  });

  it("sets the player's class from the picker", async () => {
    const fetchMock = stubFetch((path, init) => {
      if (path.endsWith("/auth/me")) return { status: 200, body: me() };
      if (path.endsWith("/character/class") && init?.method === "PUT") {
        return {
          status: 200,
          body: { ...OWN_SHEET, character_class: { id: "cl1", name: "Rogue", description: null } },
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

    expect(await screen.findByText(/Reach level 3 to choose a class/)).toBeInTheDocument();
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
