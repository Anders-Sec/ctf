import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import HomePage from "./HomePage";
import { capabilities, me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function withSession(overrides: Parameters<typeof me>[0]) {
  stubFetch(() => ({ status: 200, body: me(overrides) }));
  renderApp(<HomePage />);
}

describe("HomePage gates", () => {
  it("tells a pending guest they are waiting on approval", async () => {
    withSession({
      capabilities: capabilities({
        play: false,
        view_scoreboard: false,
        blocked_reason: "account_pending_approval",
      }),
    });

    expect(await screen.findByText(/Awaiting approval/i)).toBeInTheDocument();
  });

  it("still points a pending guest at forming a party", async () => {
    // Only gameplay waits on approval, so the party route stays useful.
    withSession({
      capabilities: capabilities({ play: false, blocked_reason: "account_pending_approval" }),
    });

    expect(await screen.findByText(/join a party in the meantime/i)).toBeInTheDocument();
  });

  it("shows the start time before the doors open", async () => {
    withSession({
      capabilities: capabilities({ play: false, blocked_reason: "event_not_started" }),
    });

    expect(await screen.findByText(/doors are still shut/i)).toBeInTheDocument();
  });

  it("distinguishes a finished event from one that has not begun", async () => {
    withSession({
      capabilities: capabilities({ play: false, blocked_reason: "event_ended" }),
    });

    expect(await screen.findByText(/crawl is over/i)).toBeInTheDocument();
  });

  it("opens up once the server says the player may play", async () => {
    withSession({ capabilities: capabilities({ play: true }) });

    expect(await screen.findByText(/dungeon is open/i)).toBeInTheDocument();
  });

  it("reports a disabled account", async () => {
    withSession({
      capabilities: capabilities({
        play: false,
        manage_party: false,
        blocked_reason: "account_disabled",
      }),
    });

    expect(await screen.findByText(/account is disabled/i)).toBeInTheDocument();
  });

  it("names the party the player marches with", async () => {
    withSession({
      team: { id: "t1", name: "The Mimics", is_leader: true },
    });

    expect(await screen.findByText("The Mimics")).toBeInTheDocument();
    expect(screen.getByText(/you lead it/i)).toBeInTheDocument();
  });
});
