import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminAnnouncementsPage from "./AdminAnnouncementsPage";
import type { Announcement } from "../api/announcements";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function announcement(overrides: Partial<Announcement> = {}): Announcement {
  return {
    id: "aaaaaaaa-0000-0000-0000-000000000001",
    title: "Lunch",
    body: "In the atrium.",
    audience: "everyone",
    created_by_name: "Dungeon Master",
    scheduled_for: null,
    sent_at: "2026-09-17T12:00:00Z",
    cancelled_at: null,
    recipient_count: 184,
    read_count: 141,
    created_at: "2026-09-17T12:00:00Z",
    ...overrides,
  };
}

function render(history: Announcement[]) {
  const mock = stubFetch((path) => {
    if (path.endsWith("/auth/me")) {
      return {
        status: 200,
        body: me({ capabilities: capabilities({ view_admin: true, administer: true }) }),
      };
    }
    if (path.includes("/admin/announcements")) {
      return { status: 200, body: history };
    }
    return { status: 200, body: {} };
  });
  renderApp(<AdminAnnouncementsPage />);
  return mock;
}

describe("AdminAnnouncementsPage", () => {
  it("shows what was said, and whether it landed", async () => {
    // The one genuinely new number. A 30% read rate on "the Crypto zone is
    // fixed" explains a lot of support questions.
    render([announcement()]);

    const row = (await screen.findByText("Lunch")).closest("li")!;
    expect(within(row).getByText(/184 sent/)).toBeInTheDocument();
    expect(within(row).getByText(/141 read \(77%\)/)).toBeInTheDocument();
  });

  it("confirms before sending, because this reaches everyone at once", async () => {
    const fetchMock = render([]);
    await screen.findByLabelText("Announcement title");

    await userEvent.type(screen.getByLabelText("Announcement title"), "Doors");
    await userEvent.type(screen.getByLabelText("Announcement message"), "Are open.");
    await userEvent.click(screen.getByRole("button", { name: "Send now" }));

    // Nothing has gone out yet.
    expect(
      fetchMock.mock.calls.some(
        ([path, init]) =>
          String(path).includes("/admin/announcements") && init?.method === "POST",
      ),
    ).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Yes" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([path, init]) =>
            String(path).includes("/admin/announcements") && init?.method === "POST",
        ),
      ).toBe(true),
    );
  });

  it("switches the action to Schedule once a time is set", async () => {
    render([]);
    await screen.findByLabelText("Announcement title");
    await userEvent.type(screen.getByLabelText("Announcement title"), "Later");
    await userEvent.type(screen.getByLabelText("Announcement message"), "Not yet.");

    await userEvent.type(screen.getByLabelText("Schedule for"), "2026-09-18T09:00");

    expect(screen.getByRole("button", { name: "Schedule" })).toBeInTheDocument();
  });

  it("offers cancel on a pending announcement and not on a sent one", async () => {
    // Pending is the one state nobody has read yet.
    render([
      announcement({ id: "p", title: "Pending", sent_at: null, scheduled_for: "2026-09-18T09:00:00Z" }),
      announcement({ id: "s", title: "Sent" }),
    ]);

    const pending = (await screen.findByText("Pending")).closest("li")!;
    const sent = screen.getByText("Sent").closest("li")!;

    expect(within(pending).getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(within(sent).queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("never offers to edit or delete something already sent", async () => {
    // The history is a record of what happened.
    render([announcement()]);
    const row = (await screen.findByText("Lunch")).closest("li")!;

    expect(within(row).queryByRole("button", { name: /edit|delete/i })).not.toBeInTheDocument();
  });

  it("re-sending prefills a new announcement rather than editing the old one", async () => {
    render([announcement()]);

    await userEvent.click(await screen.findByRole("button", { name: "Say it again" }));

    expect(screen.getByLabelText("Announcement title")).toHaveValue("Lunch");
    expect(screen.getByLabelText("Announcement message")).toHaveValue("In the atrium.");
  });

  it("marks a staff-only announcement", async () => {
    render([announcement({ audience: "staff" })]);

    expect(await screen.findByText("staff only")).toBeInTheDocument();
  });

  it("says so when nothing has been announced", async () => {
    render([]);

    expect(await screen.findByText(/nothing said yet/i)).toBeInTheDocument();
  });
});
