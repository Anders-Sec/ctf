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
    expect(screen.queryByRole("link", { name: "Manage" })).not.toBeInTheDocument();
  });

  it("defaults an admin to the player view with an Admin view button", async () => {
    render(true);

    expect(await screen.findByRole("button", { name: /admin view/i })).toBeInTheDocument();
    // Player tabs, and NOT the admin tabs, by default.
    expect(screen.getByRole("link", { name: "Challenges" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Manage" })).not.toBeInTheDocument();
  });

  it("swaps to admin-only tabs when Admin view is clicked", async () => {
    render(true);

    await userEvent.click(await screen.findByRole("button", { name: /admin view/i }));

    expect(await screen.findByRole("link", { name: "Manage" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Approvals" })).toBeInTheDocument();
    // Player tabs are gone in admin view.
    expect(screen.queryByRole("link", { name: "Challenges" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /player view/i })).toBeInTheDocument();
  });

  it("goes back to the player tabs on Player view", async () => {
    render(true);
    await userEvent.click(await screen.findByRole("button", { name: /admin view/i }));
    await userEvent.click(await screen.findByRole("button", { name: /player view/i }));

    expect(await screen.findByRole("link", { name: "Challenges" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Manage" })).not.toBeInTheDocument();
  });

  it("remembers the admin-view choice across a remount", async () => {
    render(true);
    await userEvent.click(await screen.findByRole("button", { name: /admin view/i }));
    await screen.findByRole("link", { name: "Manage" });

    // A fresh mount reads the persisted choice.
    vi.unstubAllGlobals();
    render(true);

    await waitFor(() => {
      expect(screen.getByRole("link", { name: "Manage" })).toBeInTheDocument();
    });
  });
});
