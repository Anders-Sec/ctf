import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import HintList from "./HintList";
import type { Hint } from "../api/challenges";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function hint(overrides: Partial<Hint> = {}): Hint {
  return {
    id: "h1",
    title: "Where to look",
    cost: 50,
    unlocked: false,
    available: true,
    body: null,
    ...overrides,
  };
}

/**
 * Renders and opens the disclosure.
 *
 * Hints start collapsed since spec 062 §5.1 — they used to render as a full
 * section below the body and were routinely taller than it. Every assertion
 * below is about the hints themselves, which is unchanged, so they open first
 * rather than each being rewritten.
 */
async function renderOpen(hints: Hint[], unlockBody = "Check frame 42.") {
  const mock = render(hints, unlockBody);
  await userEvent.click(await screen.findByRole("button", { name: /Hints/ }));
  return mock;
}

function render(hints: Hint[], unlockBody = "Check frame 42.") {
  const mock = stubFetch((path, init) => {
    if (path.endsWith("/auth/me")) return { status: 200, body: me() };
    if (init?.method === "POST") {
      return {
        status: 200,
        body: {
          body: unlockBody,
          cost_charged: 50,
          already_unlocked: false,
          new_total: -50,
        },
      };
    }
    return { status: 200, body: {} };
  });
  renderApp(<HintList challengeId="c1" hints={hints} />);
  return mock;
}

describe("HintList", () => {
  it("is one line until it is asked for", async () => {
    render([hint(), hint({ id: "h2", unlocked: true })]);

    // The description is what a player came to read; hints are the background
    // item that comes into play when needed.
    expect(
      await screen.findByRole("button", { name: /Hints 2 available · 1 opened/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /unlock/i })).not.toBeInTheDocument();
  });

  it("renders nothing at all when there are no hints", () => {
    const { container } = renderApp(<HintList challengeId="c1" hints={[]} />);

    expect(container.querySelector("section")).toBeNull();
  });

  it("states the cost before anything is spent", async () => {
    await renderOpen([hint({ cost: 75 })]);

    expect(
      await screen.findByRole("button", { name: /unlock — 75 XP/i }),
    ).toBeInTheDocument();
  });

  it("does not show the hint text before it is bought", async () => {
    await renderOpen([hint()]);
    await screen.findByText("Where to look");

    expect(screen.queryByText("Check frame 42.")).not.toBeInTheDocument();
  });

  it("requires a second click that names the price", async () => {
    // A one-click purchase next to the submit button is a misclick waiting to
    // happen, and the XP is gone for good.
    const mock = await renderOpen([hint({ cost: 75 })]);

    await userEvent.click(await screen.findByRole("button", { name: /unlock — 75 XP/i }));

    expect(screen.getByRole("button", { name: /spend 75 XP/i })).toBeInTheDocument();
    // Nothing has been spent yet.
    expect(mock.mock.calls.filter(([, init]) => (init as RequestInit)?.method === "POST")).toHaveLength(0);
  });

  it("reveals the hint once confirmed", async () => {
    await renderOpen([hint()]);

    await userEvent.click(await screen.findByRole("button", { name: /unlock/i }));
    await userEvent.click(screen.getByRole("button", { name: /spend 50 XP/i }));

    expect(await screen.findByText("Check frame 42.")).toBeInTheDocument();
  });

  it("can be backed out of", async () => {
    const mock = await renderOpen([hint()]);

    await userEvent.click(await screen.findByRole("button", { name: /unlock/i }));
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));

    expect(screen.getByRole("button", { name: /unlock — 50 XP/i })).toBeInTheDocument();
    expect(mock.mock.calls.filter(([, init]) => (init as RequestInit)?.method === "POST")).toHaveLength(0);
  });

  it("shows an already-unlocked hint outright", async () => {
    await renderOpen([hint({ unlocked: true, body: "Already paid for." })]);

    expect(await screen.findByText("Already paid for.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /unlock/i })).not.toBeInTheDocument();
  });

  it("says free rather than naming a price once the challenge is solved", async () => {
    await renderOpen([hint({ cost: 0 })]);

    expect(await screen.findByRole("button", { name: /reveal — free/i })).toBeInTheDocument();
    expect(screen.getByText(/already solved this challenge/i)).toBeInTheDocument();
  });

  it("explains an unavailable hint instead of offering it", async () => {
    await renderOpen([hint({ available: false })]);

    expect(await screen.findByText(/unlock the hint before this one/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /unlock/i })).not.toBeInTheDocument();
  });

  it("renders nothing when a challenge has no hints", () => {
    const { container } = renderApp(<HintList challengeId="c1" hints={[]} />);

    expect(container.querySelector("section")).toBeNull();
  });
});
