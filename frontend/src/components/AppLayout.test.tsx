import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";

import AppLayout from "./AppLayout";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  try {
    localStorage.clear();
  } catch {
    // ignore
  }
});

function render(isAdmin: boolean) {
  stubFetch((path) => {
    if (path.endsWith("/auth/me")) {
      return {
        status: 200,
        body: me({ capabilities: capabilities({ view_admin: isAdmin }) }),
      };
    }
    if (path.includes("/scoreboard/me")) {
      return {
        status: 200,
        body: {
          rank: 12,
          level: 7,
          player_count: 87,
          team_rank: 4,
          team_level: 5,
          team_count: 21,
        },
      };
    }
    return { status: 200, body: {} };
  });
  renderApp(
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<div>home</div>} />
        <Route path="/admin" element={<div>admin console</div>} />
      </Route>
    </Routes>,
  );
}

/** Since spec 064, Settings, Sign out and Admin view live behind the profile. */
async function openProfile() {
  await userEvent.click(await screen.findByRole("button", { name: /level/i }));
}

describe("AppLayout navigation", () => {
  it("shows a player the player tabs and no view toggle", async () => {
    render(false);

    expect(await screen.findByRole("link", { name: "Challenges" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Scoreboard" })).toBeInTheDocument();
    await openProfile();
    expect(screen.queryByRole("menuitem", { name: /admin view/i })).not.toBeInTheDocument();
  });

  it("defaults an admin to the player view, with the way in behind the profile", async () => {
    render(true);

    // The player view is the default, so an admin sees the event as a player
    // does until they ask not to.
    expect(await screen.findByRole("link", { name: "Challenges" })).toBeInTheDocument();
    await openProfile();
    expect(screen.getByRole("menuitem", { name: /admin view/i })).toBeInTheDocument();
  });

  it("keeps sign out and settings off the bar", async () => {
    // A once-an-event action was a permanent fixture beside Settings, which is
    // nearly as rare (spec 064 §1).
    render(false);
    await screen.findByRole("link", { name: "Challenges" });

    expect(screen.queryByRole("button", { name: /sign out/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();

    await openProfile();
    expect(screen.getByRole("menuitem", { name: /sign out/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Settings" })).toBeInTheDocument();
  });

  it("closes the profile menu on Escape", async () => {
    render(false);
    await openProfile();
    expect(screen.getByRole("menu", { name: "Profile" })).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");

    await waitFor(() =>
      expect(screen.queryByRole("menu", { name: "Profile" })).not.toBeInTheDocument(),
    );
  });

  it("closes the profile menu on an outside click", async () => {
    render(false);
    await openProfile();

    await userEvent.click(screen.getByRole("link", { name: "Challenges" }));

    await waitFor(() =>
      expect(screen.queryByRole("menu", { name: "Profile" })).not.toBeInTheDocument(),
    );
  });

  it("shows the player's own level on the bar", async () => {
    // XP is only ever visible to yourself — never another player's, and never
    // on a board (spec 064 §7.1).
    render(false);

    expect(await screen.findByText("Lv 1")).toBeInTheDocument();
  });

  it("carries rank and party rank in the profile menu", async () => {
    render(false);

    await openProfile();

    await waitFor(() => expect(screen.getByText("#12")).toBeInTheDocument());
    expect(screen.getByText("#4")).toBeInTheDocument();
  });

  it("drops the player tabs when Admin view is clicked", async () => {
    // Since spec 049 the admin area navigates by the sidebar in AdminLayout,
    // not by tabs here. All this bar does in admin view is get out of the way.
    // The route back out lives at the foot of that sidebar.
    render(true);

    await openProfile();
    await userEvent.click(screen.getByRole("menuitem", { name: /admin view/i }));

    await waitFor(() =>
      expect(screen.getByRole("link", { name: /CTF/ })).toHaveAttribute("href", "/admin"),
    );
    expect(screen.queryByRole("link", { name: "Challenges" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Scoreboard" })).not.toBeInTheDocument();
    // Offering the way in twice would be the confusing half of a toggle.
    await openProfile();
    expect(screen.queryByRole("menuitem", { name: /admin view/i })).not.toBeInTheDocument();
  });

  it("remembers the admin-view choice across a remount", async () => {
    render(true);
    await openProfile();
    await userEvent.click(screen.getByRole("menuitem", { name: /admin view/i }));
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "Challenges" })).not.toBeInTheDocument(),
    );

    // A fresh mount reads the persisted choice. The first mount is still in
    // the document — cleanup runs between tests, not within one — so this
    // asserts on the newest brand link rather than assuming there is one.
    vi.unstubAllGlobals();
    render(true);

    await waitFor(() => {
      const brands = screen.getAllByRole("link", { name: /CTF/ });
      expect(brands[brands.length - 1]).toHaveAttribute("href", "/admin");
    });
  });
});
