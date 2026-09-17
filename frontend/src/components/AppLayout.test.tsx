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
    // not by tabs here. All this bar does in admin view is get out of the way
    // and offer the route back.
    render(true);

    await userEvent.click(await screen.findByRole("button", { name: /admin view/i }));

    expect(await screen.findByRole("button", { name: /player view/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Challenges" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Scoreboard" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /CTF/ })).toHaveAttribute("href", "/admin");
  });

  it("goes back to the player tabs on Player view", async () => {
    render(true);
    await userEvent.click(await screen.findByRole("button", { name: /admin view/i }));
    await userEvent.click(await screen.findByRole("button", { name: /player view/i }));

    expect(await screen.findByRole("link", { name: "Challenges" })).toBeInTheDocument();
  });

  it("remembers the admin-view choice across a remount", async () => {
    render(true);
    await userEvent.click(await screen.findByRole("button", { name: /admin view/i }));
    await screen.findByRole("button", { name: /player view/i });

    // A fresh mount reads the persisted choice.
    vi.unstubAllGlobals();
    render(true);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /player view/i })).toBeInTheDocument();
    });
  });
});
