import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";

import AdminLayout from "./AdminLayout";
import type { Dashboard } from "../api/adminOps";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function counts(overrides: Partial<Dashboard["nav_counts"]> = {}): Dashboard["nav_counts"] {
  return {
    open_reports: 0,
    pending_approvals: 0,
    open_signals: 0,
    failed_instances: 0,
    ...overrides,
  };
}

function render(
  { nav_counts = counts(), route = "/admin" }: {
    nav_counts?: Dashboard["nav_counts"];
    route?: string;
  } = {},
) {
  stubFetch((path) => {
    if (path.endsWith("/auth/me")) {
      return {
        status: 200,
        body: me({ capabilities: capabilities({ view_admin: true, administer: true }) }),
      };
    }
    if (path.endsWith("/admin/dashboard")) {
      return {
        status: 200,
        body: {
          nav_counts,
          event: {
            name: "Autumn Crawl",
            starts_at: "2026-09-06T09:00:00Z",
            ends_at: "2026-09-08T17:00:00Z",
            running: true,
            server_time: "2026-09-06T12:00:00Z",
          },
        },
      };
    }
    return { status: 200, body: {} };
  });

  renderApp(
    <Routes>
      <Route path="/admin" element={<AdminLayout />}>
        <Route index element={<div>dashboard</div>} />
        <Route path="ops" element={<div>ops</div>} />
        <Route path="challenges" element={<div>challenges</div>} />
      </Route>
    </Routes>,
    { route },
  );
}

/** The sidebar, ignoring the drawer copy that shares its links. */
function sidebar() {
  return screen.getAllByRole("navigation", { name: "Admin sections" })[0]!;
}

describe("AdminLayout", () => {
  it("groups the sections under headings", async () => {
    render();
    await screen.findByText("dashboard");

    for (const heading of ["Operations", "Content", "Settings"]) {
      expect(within(sidebar()).getByText(heading)).toBeInTheDocument();
    }
  });

  it("lists every section in its group", async () => {
    render();
    await screen.findByText("dashboard");
    const nav = within(sidebar());

    // Operations
    for (const label of [
      "Reports & Adjustments",
      "Anti-Cheat Signals",
      "Metrics",
      "System AI",
      "Live Instances",
      "Approvals",
      "Audit Log",
      "Announcements",
      "Platform Health",
    ]) {
      expect(nav.getByRole("link", { name: new RegExp(label) })).toBeInTheDocument();
    }
    // Content and Settings
    for (const label of ["Challenges", "Skills", "Classes", "Achievements", "Map"]) {
      expect(nav.getByRole("link", { name: label })).toBeInTheDocument();
    }
    for (const label of [
      "Event",
      "Theme",
      "Container Templates",
      "Email Delivery",
      "Export",
      "Data & Reset",
    ]) {
      expect(nav.getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("uses practical names, never themed ones", async () => {
    // The standing Phase 3 decision: dungeon flavour is player-facing. "Live
    // Instances" is faster to act on than "Dungeons" when something is broken.
    render();
    await screen.findByText("dashboard");
    const nav = within(sidebar());

    expect(nav.queryByRole("link", { name: "Dungeons" })).not.toBeInTheDocument();
    expect(nav.queryByRole("link", { name: "Manage" })).not.toBeInTheDocument();
    expect(nav.queryByRole("link", { name: "Console" })).not.toBeInTheDocument();
  });

  it("marks the active section", async () => {
    render({ route: "/admin/ops" });
    await screen.findByText("ops");

    expect(
      within(sidebar()).getByRole("link", { name: /Reports & Adjustments/ }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("does not mark Dashboard active on a nested admin route", async () => {
    // `/admin` is a prefix of every other admin path, so without an exact match
    // Dashboard would light up everywhere.
    render({ route: "/admin/challenges" });
    await screen.findByText("challenges");

    expect(within(sidebar()).getByRole("link", { name: "Dashboard" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("badges work that is waiting", async () => {
    render({ nav_counts: counts({ open_reports: 3, pending_approvals: 7 }) });
    await screen.findByText("dashboard");
    const nav = within(sidebar());

    await waitFor(() =>
      expect(nav.getByRole("link", { name: /Reports & Adjustments/ })).toHaveTextContent("3"),
    );
    expect(nav.getByRole("link", { name: /Approvals/ })).toHaveTextContent("7");
  });

  it("shows no badge at zero", async () => {
    // A zero badge is noise that teaches you to stop reading badges.
    render({ nav_counts: counts({ open_reports: 0 }) });
    await screen.findByText("dashboard");

    expect(
      within(sidebar()).getByRole("link", { name: /Reports & Adjustments/ }),
    ).not.toHaveTextContent("0");
  });

  it("carries the event clock, because it changes how every page reads", async () => {
    render();
    await screen.findByText("dashboard");

    const nav = within(sidebar());
    expect(await nav.findByText("Autumn Crawl")).toBeInTheDocument();
    expect(nav.getByText("running")).toBeInTheDocument();
  });

  it("offers the way back to the player view at the foot of the sidebar", async () => {
    render();
    await screen.findByText("dashboard");

    expect(within(sidebar()).getByRole("button", { name: /player view/i })).toBeInTheDocument();
  });

  it("opens a drawer on narrow screens and closes it on Escape", async () => {
    render();
    await screen.findByText("dashboard");

    await userEvent.click(screen.getByRole("button", { name: "Sections" }));
    await waitFor(() =>
      expect(screen.getAllByRole("navigation", { name: "Admin sections" })).toHaveLength(2),
    );

    await userEvent.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.getAllByRole("navigation", { name: "Admin sections" })).toHaveLength(1),
    );
  });

  it("closes the drawer once you have navigated", async () => {
    render();
    await screen.findByText("dashboard");
    await userEvent.click(screen.getByRole("button", { name: "Sections" }));

    const drawer = screen.getAllByRole("navigation", { name: "Admin sections" })[1]!;
    await userEvent.click(within(drawer).getByRole("link", { name: /Reports & Adjustments/ }));

    await waitFor(() =>
      expect(screen.getAllByRole("navigation", { name: "Admin sections" })).toHaveLength(1),
    );
  });
});
