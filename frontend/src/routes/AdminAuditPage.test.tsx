import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminAuditPage from "./AdminAuditPage";
import type { AuditEntry } from "../api/adminOps";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function entry(overrides: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id: crypto.randomUUID(),
    action: "score.adjust",
    actor_user_id: "aaaaaaaa-0000-0000-0000-000000000001",
    actor_name: "Dungeon Master",
    target_type: "user",
    target_id: "bbbbbbbb-0000-0000-0000-000000000002",
    reason: "Compensation for a broken challenge",
    metadata: { points: 25 },
    request_id: "req-123",
    created_at: "2026-09-17T12:00:00Z",
    ...overrides,
  };
}

function render(entries: AuditEntry[], total = entries.length) {
  const mock = stubFetch((path) => {
    if (path.endsWith("/auth/me")) {
      return { status: 200, body: me({ user: { ...me().user, role: "organizer" } }) };
    }
    if (path.includes("/admin/audit-log/actions")) {
      return { status: 200, body: ["score.adjust", "user.approve"] };
    }
    if (path.includes("/admin/audit-log")) {
      return { status: 200, body: { total, entries } };
    }
    return { status: 200, body: {} };
  });
  renderApp(<AdminAuditPage />, { route: "/admin/audit" });
  return mock;
}

describe("AdminAuditPage", () => {
  it("lists entries with actor, action, target and reason", async () => {
    render([entry()]);

    expect(await screen.findByText("Dungeon Master")).toBeInTheDocument();
    // Scoped to the table: "score.adjust" is also an option in the filter.
    const table = screen.getByRole("table");
    expect(within(table).getByText("score.adjust")).toBeInTheDocument();
    expect(
      within(table).getByText("Compensation for a broken challenge"),
    ).toBeInTheDocument();
  });

  it("renders a null actor as the system, not as a blank", async () => {
    // Scheduled cleanup and automatic leadership transfer act on nobody's
    // behalf; that is not the same as an unknown person.
    render([entry({ actor_user_id: null, actor_name: null })]);

    expect(await screen.findByText("system")).toBeInTheDocument();
  });

  it("shows an absolute timestamp, not only a relative one", async () => {
    // A timeline cannot be reconstructed from "3 hours ago".
    render([entry()]);
    await screen.findByText("Dungeon Master");

    expect(screen.getByText(/ago|just now/)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(String(new Date("2026-09-17T12:00:00Z").getFullYear()))))
      .toBeInTheDocument();
  });

  it("keeps the metadata and request id behind an expander", async () => {
    render([entry()]);
    await screen.findByText("Dungeon Master");

    expect(screen.queryByText(/req-123/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Details" }));

    expect(screen.getByText(/req-123/)).toBeInTheDocument();
    expect(screen.getByText(/"points": 25/)).toBeInTheDocument();
  });

  it("offers no way to edit or delete an entry", async () => {
    // The table is append-only by design, so it should not suggest otherwise.
    render([entry()]);
    await screen.findByText("Dungeon Master");

    expect(screen.queryByRole("button", { name: /delete|edit|remove/i })).not.toBeInTheDocument();
  });

  it("populates the action filter from the actions actually present", async () => {
    render([entry()]);

    // The options arrive on their own query, so await them rather than the
    // select they hang off.
    expect(await screen.findByRole("option", { name: "score.adjust" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "user.approve" })).toBeInTheDocument();
  });

  it("sends the chosen filters to the server", async () => {
    // Server-side, because the log is bigger than a page.
    const fetchMock = render([entry()]);
    await screen.findByText("Dungeon Master");

    await userEvent.selectOptions(screen.getByLabelText("Action"), "user.approve");

    const called = fetchMock.mock.calls.some(([path]) =>
      String(path).includes("action=user.approve"),
    );
    expect(called).toBe(true);
  });

  it("defaults to the last 24 hours rather than page one of everything", async () => {
    const fetchMock = render([entry()]);
    await screen.findByText("Dungeon Master");

    const called = fetchMock.mock.calls.some(([path]) => String(path).includes("since="));
    expect(called).toBe(true);
  });

  it("reports the total matching, not the page size", async () => {
    render([entry()], 250);

    expect(await screen.findByText(/250 entries/)).toBeInTheDocument();
  });

  it("says so when the window is empty", async () => {
    render([], 0);

    expect(await screen.findByText(/nothing recorded/i)).toBeInTheDocument();
  });

  it("renders an entry whose target has since been deleted", async () => {
    // The log outlives its targets, which is the common case for a challenge
    // that was removed.
    render([entry({ target_id: null, target_type: "challenge" })]);

    expect(await screen.findByText("challenge")).toBeInTheDocument();
  });
});
