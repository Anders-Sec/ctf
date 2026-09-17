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

describe("AppLayout navigation", () => {
  it("shows a player the player tabs and no view toggle", async () => {
    render(false);

    expect(await screen.findByRole("link", { name: "Challenges" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Scoreboard" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /admin view/i })).not.toBeInTheDocument();
  });

  it("defaults an admin to the player view with an Admin view button", async () => {
    render(true);

    expect(await screen.findByRole("button", { name: /admin view/i })).toBeInTheDocument();
    // The player view is the default, so an admin sees the event as a player
    // does until they ask not to.
    expect(screen.getByRole("link", { name: "Challenges" })).toBeInTheDocument();
  });

  it("drops the player tabs when Admin view is clicked", async () => {
    // Since spec 049 the admin area navigates by the sidebar in AdminLayout,
    // not by tabs here. All this bar does in admin view is get out of the way.
    // The route back out lives at the foot of that sidebar.
    render(true);

    await userEvent.click(await screen.findByRole("button", { name: /admin view/i }));

    await waitFor(() =>
      expect(screen.getByRole("link", { name: /CTF/ })).toHaveAttribute("href", "/admin"),
    );
    expect(screen.queryByRole("link", { name: "Challenges" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Scoreboard" })).not.toBeInTheDocument();
    // Offering the way in twice would be the confusing half of a toggle.
    expect(screen.queryByRole("button", { name: /admin view/i })).not.toBeInTheDocument();
  });

  it("remembers the admin-view choice across a remount", async () => {
    render(true);
    await userEvent.click(await screen.findByRole("button", { name: /admin view/i }));
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
