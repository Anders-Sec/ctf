import { screen } from "@testing-library/react";
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
    {
      skill_id: "s1",
      name: "Hacking",
      xp: 600,
      level: 3,
      xp_into_level: 0,
      xp_to_next: 600,
    },
  ],
};

const PUBLIC_SHEET = {
  user_id: "22222222-2222-2222-2222-222222222222",
  display_name: "Sir Solves",
  has_avatar: false,
  level: 2,
  skills: [{ skill_id: "s1", name: "Hacking", level: 2 }],
};

describe("CharacterSheetPage", () => {
  it("shows the player's own level, total XP and skills", async () => {
    stubFetch((path) => {
      if (path.endsWith("/auth/me")) return { status: 200, body: me() };
      if (path.endsWith("/character/me")) return { status: 200, body: OWN_SHEET };
      return { status: 200, body: {} };
    });

    renderApp(<CharacterSheetPage />, { route: "/character" });

    expect(await screen.findByText("600 XP total")).toBeInTheDocument();
    expect(screen.getByText("Hacking")).toBeInTheDocument();
    expect(screen.getByText(/rank #2/)).toBeInTheDocument();
  });

  it("shows another player's public sheet without a rank", async () => {
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
    expect(screen.getByText(/Level 2 adventurer/)).toBeInTheDocument();
    expect(screen.queryByText(/rank #/)).not.toBeInTheDocument();
  });
});
