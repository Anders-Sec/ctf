import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import NotificationCentre from "./NotificationCentre";
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

const FEED = {
  unread: 1,
  items: [
    {
      id: "n1",
      kind: "achievement",
      title: "First Blood",
      body: "Logged: First Blood.",
      link: "/character",
      read: false,
      created_at: "2026-09-08T10:00:00Z",
    },
  ],
};

beforeEach(() => {
  FakeSocket.last = null;
  vi.stubGlobal("WebSocket", FakeSocket as unknown as typeof WebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function render(feed: unknown = FEED) {
  const mock = stubFetch((path) => {
    if (path.endsWith("/notifications")) return { status: 200, body: feed };
    return { status: 200, body: { message: "ok" } };
  });
  renderApp(<NotificationCentre />);
  return mock;
}

describe("NotificationCentre", () => {
  it("shows the unread count on the bell", async () => {
    render();

    expect(
      await screen.findByRole("button", { name: /1 unread/i }),
    ).toBeInTheDocument();
  });

  it("opens the backlog, which is the record whether or not a socket ran", async () => {
    render();

    await userEvent.click(await screen.findByRole("button", { name: /notifications/i }));

    const panel = await screen.findByRole("dialog", { name: "Notifications" });
    expect(panel).toHaveTextContent("First Blood");
  });

  it("pops a toast when one arrives live", async () => {
    render({ unread: 0, items: [] });
    await waitFor(() => expect(FakeSocket.last).not.toBeNull());

    act(() => {
      FakeSocket.last!.onmessage?.({
        data: JSON.stringify({
          id: "n9",
          kind: "level_up",
          title: "Level 4",
          body: "The number went up.",
          link: null,
          read: false,
          created_at: "2026-09-08T10:05:00Z",
        }),
      });
    });

    expect(await screen.findByRole("status")).toHaveTextContent("Level 4");
  });

  it("does not pop the same notification twice", async () => {
    render({ unread: 0, items: [] });
    await waitFor(() => expect(FakeSocket.last).not.toBeNull());

    const frame = {
      data: JSON.stringify({
        id: "n9",
        kind: "system",
        title: "Once Only",
        body: "x",
        link: null,
        read: false,
        created_at: "2026-09-08T10:05:00Z",
      }),
    };
    act(() => {
      FakeSocket.last!.onmessage?.(frame);
      FakeSocket.last!.onmessage?.(frame);
    });

    expect(await screen.findAllByRole("status")).toHaveLength(1);
  });

  it("marks everything read", async () => {
    const fetchMock = render();

    await userEvent.click(await screen.findByRole("button", { name: /notifications/i }));
    await userEvent.click(screen.getByRole("button", { name: "Mark all read" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([path]) =>
        String(path).endsWith("/notifications/read"),
      );
      expect(call?.[1]?.method).toBe("POST");
    });
  });

  it("says when it is not connected, without pretending the feed is wrong", async () => {
    render();
    await waitFor(() => expect(FakeSocket.last).not.toBeNull());

    act(() => FakeSocket.last!.onclose?.());
    await userEvent.click(await screen.findByRole("button", { name: /notifications/i }));

    expect(screen.getByText(/not connected/i)).toBeInTheDocument();
    // The backlog is still shown: it is the record, the socket is a nicety.
    expect(screen.getByRole("dialog")).toHaveTextContent("First Blood");
  });
});
