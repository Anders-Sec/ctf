import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminUsersPage from "./AdminUsersPage";
import type { AdminUser, UserDetail } from "../api/admin";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function user(overrides: Partial<AdminUser> = {}): AdminUser {
  return {
    id: "11111111-0000-0000-0000-000000000001",
    email: "rin@example.com",
    display_name: "Rin",
    source: "guest",
    role: "player",
    status: "active",
    created_at: "2026-09-01T09:00:00Z",
    approved_at: "2026-09-01T10:00:00Z",
    last_login_at: "2026-09-17T09:00:00Z",
    party_name: "The Bold",
    solve_count: 4,
    xp: 480,
    ...overrides,
  };
}

function detail(overrides: Partial<UserDetail> = {}): UserDetail {
  return {
    user: user(),
    entra_object_id: null,
    approved_by_name: "Dungeon Master",
    disabled_reason: null,
    assistant_blocked: false,
    level: 3,
    hints_used: 2,
    achievement_count: 5,
    class_name: "Rogue",
    parties: [],
    recent_activity: [],
    current_wall: "Sealed Vault",
    unlocked_themes: [],
    grantable_themes: [],
    ...overrides,
  };
}

function render(users: AdminUser[], detailBody: UserDetail = detail()) {
  const mock = stubFetch((path) => {
    if (path.endsWith("/auth/me")) {
      return {
        status: 200,
        body: me({ capabilities: capabilities({ view_admin: true, administer: true }) }),
      };
    }
    if (path.includes("/admin/email/deliveries")) {
      // The drawer shows a guest's sign-in links (spec 055 §4).
      return { status: 200, body: { total: 0, entries: [] } };
    }
    if (/\/admin\/users\/[0-9a-f-]+$/.test(path)) {
      return { status: 200, body: detailBody };
    }
    if (path.includes("/admin/users/approve")) {
      return { status: 200, body: { total: 1, users: [] } };
    }
    if (path.includes("/admin/users")) {
      return { status: 200, body: { total: users.length, users } };
    }
    return { status: 200, body: {} };
  });
  renderApp(<AdminUsersPage />, { route: "/admin/users" });
  return mock;
}

describe("AdminUsersPage", () => {
  it("shows the roster columns that tell a player from a dormant account", async () => {
    render([user()]);
    const row = (await screen.findByRole("button", { name: "Rin" })).closest("tr")!;

    expect(within(row).getByText("rin@example.com")).toBeInTheDocument();
    expect(within(row).getByText("The Bold")).toBeInTheDocument();
    expect(within(row).getByText("4")).toBeInTheDocument();
    expect(within(row).getByText("480")).toBeInTheDocument();
  });

  it("marks a staff account but does not repeat 'player' 200 times", async () => {
    render([user(), user({ id: "22222222-0000-0000-0000-000000000002", display_name: "Boss", role: "admin" })]);
    await screen.findByRole("button", { name: "Rin" });

    expect(screen.getByText("admin")).toBeInTheDocument();
    expect(screen.queryByText("player")).not.toBeInTheDocument();
  });

  it("names a status in words, never by colour alone", async () => {
    render([user({ status: "disabled" })]);

    expect(await screen.findByText("disabled")).toBeInTheDocument();
  });

  it("filters by chip, server-side", async () => {
    const fetchMock = render([user()]);
    await screen.findByRole("button", { name: "Rin" });

    await userEvent.click(screen.getByRole("button", { name: "Pending" }));

    await waitFor(() => {
      const called = fetchMock.mock.calls.some(([path]) =>
        String(path).includes("status=pending_approval"),
      );
      expect(called).toBe(true);
    });
  });

  it("searches server-side", async () => {
    const fetchMock = render([user()]);
    await screen.findByRole("button", { name: "Rin" });

    await userEvent.type(screen.getByLabelText("Search users"), "vex");

    await waitFor(() => {
      const called = fetchMock.mock.calls.some(([path]) => String(path).includes("search=vex"));
      expect(called).toBe(true);
    });
  });

  it("offers bulk approve only for selected accounts that are actually pending", async () => {
    // 200 guests do not get approved one at a time, and approving an already
    // active account is not an action.
    render([user({ status: "active" })]);
    await screen.findByRole("button", { name: "Rin" });

    await userEvent.click(screen.getByLabelText("Select Rin"));

    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("bulk approves the pending selection", async () => {
    const fetchMock = render([user({ status: "pending_approval" })]);
    await screen.findByRole("button", { name: "Rin" });

    await userEvent.click(screen.getByLabelText("Select Rin"));
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      const called = fetchMock.mock.calls.some(([path]) =>
        String(path).includes("/admin/users/approve"),
      );
      expect(called).toBe(true);
    });
  });

  it("opens a drawer without moving the list", async () => {
    render([user()]);

    await userEvent.click(await screen.findByRole("button", { name: "Rin" }));

    const drawer = await screen.findByRole("dialog", { name: "User detail" });
    expect(within(drawer).getByText("Rogue")).toBeInTheDocument();
    expect(within(drawer).getByText("Sealed Vault")).toBeInTheDocument();
    // The row is still there underneath.
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("never offers to delete an account", async () => {
    // Solves, audit entries and party history cannot survive a delete.
    render([user()]);
    await userEvent.click(await screen.findByRole("button", { name: "Rin" }));
    const drawer = await screen.findByRole("dialog", { name: "User detail" });

    expect(within(drawer).queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
  });

  it("offers re-enable for a disabled account, and disable otherwise", async () => {
    render([user({ status: "disabled" })], detail({ user: user({ status: "disabled" }) }));
    await userEvent.click(await screen.findByRole("button", { name: "Rin" }));
    const drawer = await screen.findByRole("dialog", { name: "User detail" });

    expect(within(drawer).getByRole("button", { name: "Re-enable" })).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "Disable" })).not.toBeInTheDocument();
  });

  it("offers a resend only for a guest", async () => {
    const entra = user({ source: "entra" });
    render([entra], detail({ user: entra }));
    await userEvent.click(await screen.findByRole("button", { name: "Rin" }));
    const drawer = await screen.findByRole("dialog", { name: "User detail" });

    expect(
      within(drawer).queryByRole("button", { name: /resend sign-in link/i }),
    ).not.toBeInTheDocument();
  });

  it("closes the drawer on Escape", async () => {
    render([user()]);
    await userEvent.click(await screen.findByRole("button", { name: "Rin" }));
    await screen.findByRole("dialog", { name: "User detail" });

    await userEvent.keyboard("{Escape}");

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "User detail" })).not.toBeInTheDocument(),
    );
  });

  it("says so when nobody matches", async () => {
    render([]);

    expect(await screen.findByText(/nobody matches that/i)).toBeInTheDocument();
  });

  it("toggles a secret theme grant, and offers only the grantable ones", async () => {
    const fetchMock = render(
      [user()],
      detail({ grantable_themes: ["dnd", "mr-anderson"], unlocked_themes: ["dnd"] }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Rin" }));
    const drawer = await screen.findByRole("dialog", { name: "User detail" });

    // Held shows as on; the everyday themes are not offered at all, because
    // "granting" Parchment would be a control that does nothing (spec 058 §5.1).
    expect(within(drawer).getByRole("checkbox", { name: "DND" })).toBeChecked();
    expect(within(drawer).queryByRole("checkbox", { name: "Parchment" })).toBeNull();

    await userEvent.click(
      within(drawer).getByRole("checkbox", { name: "The Mr. Anderson" }),
    );

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([path]) =>
        String(path).includes("/theme-grant"),
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        theme: "mr-anderson",
        granted: true,
      });
    });
  });

  it("takes a granted theme back", async () => {
    const fetchMock = render(
      [user()],
      detail({ grantable_themes: ["dnd"], unlocked_themes: ["dnd"] }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Rin" }));
    const drawer = await screen.findByRole("dialog", { name: "User detail" });

    await userEvent.click(within(drawer).getByRole("checkbox", { name: "DND" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([path]) =>
        String(path).includes("/theme-grant"),
      );
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        theme: "dnd",
        granted: false,
      });
    });
  });

  it("shows no theme section when nothing is grantable", async () => {
    render([user()]);
    await userEvent.click(await screen.findByRole("button", { name: "Rin" }));
    const drawer = await screen.findByRole("dialog", { name: "User detail" });

    expect(within(drawer).queryByText("Secret themes")).not.toBeInTheDocument();
  });
});
