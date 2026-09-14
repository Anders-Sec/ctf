import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AnnouncementComposer from "./AnnouncementComposer";
import { renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function render(recipients = 42) {
  const mock = stubFetch((path) => {
    if (path.endsWith("/admin/announcements")) {
      return { status: 200, body: { recipients } };
    }
    return { status: 200, body: {} };
  });
  renderApp(<AnnouncementComposer />);
  return mock;
}

async function compose(title = "Crypto is back", body = "The wing is fixed.") {
  await userEvent.type(screen.getByLabelText("Announcement title"), title);
  await userEvent.type(screen.getByLabelText("Announcement message"), body);
}

describe("AnnouncementComposer", () => {
  it("will not send an empty announcement", () => {
    render();

    expect(screen.getByRole("button", { name: "Send announcement" })).toBeDisabled();
  });

  it("asks for confirmation before reaching 200 people", async () => {
    const fetchMock = render();
    await compose();

    await userEvent.click(screen.getByRole("button", { name: "Send announcement" }));

    // Nothing has gone out yet — the first click only arms it.
    expect(screen.getByText(/cannot be recalled\. Send it\?/i)).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(([path]) =>
        String(path).endsWith("/admin/announcements"),
      ),
    ).toHaveLength(0);
  });

  it("sends once confirmed, and says how many it reached", async () => {
    const fetchMock = render(42);
    await compose();

    await userEvent.click(screen.getByRole("button", { name: "Send announcement" }));
    await userEvent.click(screen.getByRole("button", { name: "Yes, send it" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path, init]) =>
          String(path).endsWith("/admin/announcements") && init?.method === "POST",
      );
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        title: "Crypto is back",
        body: "The wing is fixed.",
      });
    });
    expect(await screen.findByText("Sent to 42 players.")).toBeInTheDocument();
  });

  it("can be cancelled while armed", async () => {
    const fetchMock = render();
    await compose();

    await userEvent.click(screen.getByRole("button", { name: "Send announcement" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(
      screen.getByRole("button", { name: "Send announcement" }),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(([path]) =>
        String(path).endsWith("/admin/announcements"),
      ),
    ).toHaveLength(0);
  });

  it("disarms if the message is edited after arming", async () => {
    render();
    await compose();
    await userEvent.click(screen.getByRole("button", { name: "Send announcement" }));

    await userEvent.type(screen.getByLabelText("Announcement message"), " Again.");

    // Editing after confirming would otherwise send text nobody confirmed.
    expect(screen.queryByRole("button", { name: "Yes, send it" })).not.toBeInTheDocument();
  });
});
