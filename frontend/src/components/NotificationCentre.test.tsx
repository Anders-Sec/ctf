import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import NotificationCentre from "./NotificationCentre";
import { KIND_META } from "./notificationKinds";
import { NOTIFICATION_KINDS } from "../api/notifications";
import { renderApp, stubFetch } from "../test/utils";

/** jsdom has no WebSocket. This one records the instance so a test can push a
 *  frame through it, which is the only way to exercise live delivery. */
class FakeSocket {
  static last: FakeSocket | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public url: string) {
    FakeSocket.last = this;
    queueMicrotask(() => this.onopen?.());
  }
  close() {}
}

function item(overrides: Record<string, unknown> = {}) {
  return {
    id: "n1",
    kind: "achievement",
    title: "First Blood",
    body: "Logged: First Blood.",
    link: "/character",
    read: false,
    created_at: "2026-09-08T10:00:00Z",
    ...overrides,
  };
}

const FEED = { unread: 1, items: [item()] };

beforeEach(() => {
  FakeSocket.last = null;
  vi.stubGlobal("WebSocket", FakeSocket as unknown as typeof WebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function render(feed: unknown = FEED) {
  const mock = stubFetch((path) => {
    if (path.endsWith("/notifications")) return { status: 200, body: feed };
    return { status: 200, body: { message: "ok" } };
  });
  renderApp(<NotificationCentre />);
  return mock;
}

async function openInbox() {
  await userEvent.click(await screen.findByRole("button", { name: /inbox/i }));
  return screen.getByRole("dialog", { name: "Inbox" });
}

function push(frame: Record<string, unknown>) {
  act(() => {
    FakeSocket.last!.onmessage?.({ data: JSON.stringify(frame) });
  });
}

describe("the kind map", () => {
  it("places every kind in exactly one tab", () => {
    // The test that stops a tenth kind quietly vanishing from both tabs.
    for (const kind of NOTIFICATION_KINDS) {
      expect(KIND_META[kind]).toBeDefined();
      expect(["yours", "event"]).toContain(KIND_META[kind].tab);
    }
    expect(Object.keys(KIND_META).sort()).toEqual([...NOTIFICATION_KINDS].sort());
  });
});

describe("NotificationCentre", () => {
  it("shows the unread count on the bell", async () => {
    render();

    expect(await screen.findByRole("button", { name: /1 unread/i })).toBeInTheDocument();
  });

  it("opens the backlog, which is the record whether or not a socket ran", async () => {
    render();

    expect(await openInbox()).toHaveTextContent("First Blood");
  });

  it("says when it is not connected, without pretending the feed is wrong", async () => {
    render();
    await waitFor(() => expect(FakeSocket.last).not.toBeNull());

    act(() => FakeSocket.last!.onclose?.());
    const panel = await openInbox();

    expect(screen.getByText(/not connected/i)).toBeInTheDocument();
    // The backlog is still shown: it is the record, the socket is a nicety.
    expect(panel).toHaveTextContent("First Blood");
  });

  it("marks everything read", async () => {
    const fetchMock = render();
    await openInbox();

    await userEvent.click(screen.getByRole("button", { name: "Mark all read" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([path]) =>
        String(path).endsWith("/notifications/read"),
      );
      expect(call?.[1]?.method).toBe("POST");
    });
  });

  describe("two tabs", () => {
    const MIXED = {
      unread: 2,
      items: [
        item({ id: "a", kind: "level_up", title: "Level 4" }),
        item({ id: "b", kind: "boss_kill", title: "Rin felled it" }),
      ],
    };

    it("separates what happened to you from what happened", async () => {
      render(MIXED);
      const panel = await openInbox();

      // A player checking "did I level" and one checking "what did I miss" are
      // doing different jobs (spec 065 §2).
      expect(within(panel).getByText("Level 4")).toBeInTheDocument();
      expect(within(panel).queryByText("Rin felled it")).not.toBeInTheDocument();

      await userEvent.click(within(panel).getByRole("button", { name: /Event/ }));

      expect(within(panel).getByText("Rin felled it")).toBeInTheDocument();
      expect(within(panel).queryByText("Level 4")).not.toBeInTheDocument();
    });

    it("counts each tab separately, and the badge is the sum", async () => {
      render(MIXED);

      expect(await screen.findByRole("button", { name: /2 unread/i })).toBeInTheDocument();
      const panel = await openInbox();
      expect(within(panel).getByRole("button", { name: /Yours 1/ })).toBeInTheDocument();
      expect(within(panel).getByRole("button", { name: /Event 1/ })).toBeInTheDocument();
    });

    it("names the kind as text, never only as a colour", async () => {
      render(MIXED);
      const panel = await openInbox();

      // Nine near-identical glyphs is exactly the case spec 048's rule is for.
      // Scoped to the row: "Level up" is also an option in the kind filter.
      const row = within(panel).getByText("Level 4").closest("div")!;
      expect(within(row.parentElement!).getByText("Level up")).toBeInTheDocument();
    });

    it("filters within a tab, offering only that tab's kinds", async () => {
      render(MIXED);
      const panel = await openInbox();

      const filter = within(panel).getByLabelText("Filter by kind");
      expect(within(filter).getByRole("option", { name: "Level up" })).toBeInTheDocument();
      expect(within(filter).queryByRole("option", { name: "Boss kill" })).toBeNull();
    });
  });

  describe("clearing", () => {
    it("clears one row", async () => {
      const fetchMock = render();
      await openInbox();

      await userEvent.click(screen.getByRole("button", { name: "Clear First Blood" }));

      await waitFor(() => {
        const call = fetchMock.mock.calls.find(([path]) =>
          String(path).includes("/notifications/n1/dismiss"),
        );
        expect(call).toBeTruthy();
      });
    });

    it("scopes clear-all to the visible tab", async () => {
      const fetchMock = render({
        unread: 1,
        items: [item({ id: "b", kind: "boss_kill", title: "Rin felled it" })],
      });
      const panel = await openInbox();
      await userEvent.click(within(panel).getByRole("button", { name: /Event/ }));

      await userEvent.click(within(panel).getByRole("button", { name: "Clear Event" }));

      await waitFor(() => {
        const call = fetchMock.mock.calls.find(([path]) =>
          String(path).endsWith("/notifications/dismiss"),
        );
        // Clearing the news must not take a player's own record with it.
        const sent = JSON.parse(String(call?.[1]?.body)).kinds as string[];
        expect(sent).toContain("boss_kill");
        expect(sent).not.toContain("level_up");
      });
    });

    it("asks before clearing your own record", async () => {
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
      const fetchMock = render();
      await openInbox();

      await userEvent.click(screen.getByRole("button", { name: "Clear Yours" }));

      expect(confirm).toHaveBeenCalled();
      expect(
        fetchMock.mock.calls.some(([path]) =>
          String(path).endsWith("/notifications/dismiss"),
        ),
      ).toBe(false);
    });
  });

  describe("toasts", () => {
    it("pops one when a personal event arrives live", async () => {
      render({ unread: 0, items: [] });
      await waitFor(() => expect(FakeSocket.last).not.toBeNull());

      push(item({ id: "n9", kind: "level_up", title: "Level 4", link: null }));

      expect(await screen.findByRole("status")).toHaveTextContent("Level 4");
    });

    it("pops one for an announcement, which is worth interrupting for", async () => {
      render({ unread: 0, items: [] });
      await waitFor(() => expect(FakeSocket.last).not.toBeNull());

      push(item({ id: "n9", kind: "announcement", title: "Network is back", link: null }));

      expect(await screen.findByRole("status")).toHaveTextContent("Network is back");
    });

    it("stays quiet for a boss kill", async () => {
      render({ unread: 0, items: [] });
      await waitFor(() => expect(FakeSocket.last).not.toBeNull());

      push(item({ id: "n9", kind: "boss_kill", title: "Rin felled it", link: null }));

      // Interesting once and irrelevant the forty-first time. It lands in the
      // inbox and bumps the badge instead (spec 065 §5).
      await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    });

    it("has nothing to click, and blocks nothing underneath", async () => {
      render({ unread: 0, items: [] });
      await waitFor(() => expect(FakeSocket.last).not.toBeNull());

      push(item({ id: "n9", kind: "level_up", title: "Level 4", link: null }));
      const toast = await screen.findByRole("status");

      // "I'm always clicking out of them" — so make them impossible to click.
      expect(within(toast).queryByRole("button")).toBeNull();
      expect(toast.className).toContain("pointer-events-none");
    });

    it("does not pop the same notification twice", async () => {
      render({ unread: 0, items: [] });
      await waitFor(() => expect(FakeSocket.last).not.toBeNull());

      const frame = item({ id: "n9", kind: "level_up", title: "Once Only", link: null });
      push(frame);
      push(frame);

      expect(await screen.findAllByRole("status")).toHaveLength(1);
    });

    it("shows at most three at once", async () => {
      render({ unread: 0, items: [] });
      await waitFor(() => expect(FakeSocket.last).not.toBeNull());

      for (let index = 0; index < 5; index += 1) {
        push(item({ id: `n${index}`, kind: "level_up", title: `Level ${index}`, link: null }));
      }

      // One solve can award an achievement, a level and the zone it opened.
      expect(await screen.findAllByRole("status")).toHaveLength(3);
    });
  });
});

describe("focus (spec 071)", () => {
  it("moves focus into the inbox when it opens", async () => {
    render();
    const panel = await openInbox();

    expect(panel).toContainElement(document.activeElement as HTMLElement);
  });

  it("closes on Escape and gives focus back to the inbox button", async () => {
    render();
    const button = await screen.findByRole("button", { name: /inbox/i });
    await openInbox();

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "Inbox" })).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });

  it("keeps Tab inside the inbox", async () => {
    render();
    const panel = await openInbox();

    for (let index = 0; index < 8; index += 1) {
      await userEvent.tab();
      expect(panel).toContainElement(document.activeElement as HTMLElement);
    }
  });
});
