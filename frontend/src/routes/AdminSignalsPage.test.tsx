import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminSignalsPage from "./AdminSignalsPage";
import type { Finding } from "../api/signals";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    signal_type: "shared_wrong_answer",
    subject_key: "key1",
    participants: [
      { user_id: "u1", display_name: "Ada" },
      { user_id: "u2", display_name: "Bram" },
    ],
    challenge_title: "Packet Puzzle",
    evidence: { value: "flag{tpyo-in-both}", player_count: 2 },
    innocent_explanation: "An obvious guess, or they were sitting together.",
    dismissed: false,
    ...overrides,
  };
}

function render(findings: Finding[], timelineEvents: unknown[] = []) {
  const mock = stubFetch((path, init) => {
    if (path.endsWith("/auth/me")) return { status: 200, body: me() };
    if (path.includes("/timeline")) {
      return {
        status: 200,
        body: { user_id: "u1", display_name: "Ada", events: timelineEvents },
      };
    }
    if (init?.method === "POST") return { status: 200, body: { message: "Dismissed." } };
    return {
      status: 200,
      body: {
        counts: { shared_wrong_answer: findings.length },
        findings: { shared_wrong_answer: findings },
      },
    };
  });
  renderApp(<AdminSignalsPage />);
  return mock;
}

describe("AdminSignalsPage", () => {
  it("frames findings as things to look at, not accusations", async () => {
    render([finding()]);

    // The "not" is emphasised, which splits the text node — match on the
    // paragraph's whole content rather than a single node.
    expect(
      await screen.findByText(
        (_content, element) =>
          element?.tagName === "P" &&
          /not\s+accusations/i.test(element.textContent ?? ""),
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/nothing on this page changes a score/i)).toBeInTheDocument();
  });

  it("shows the innocent explanation beside the evidence", async () => {
    render([finding()]);

    expect(
      await screen.findByText(/an obvious guess, or they were sitting together/i),
    ).toBeInTheDocument();
  });

  it("uses plain language rather than the raw signal name", async () => {
    render([finding()]);

    expect(
      await screen.findByText(/identical unusual wrong answer/i),
    ).toBeInTheDocument();
  });

  it("shows the evidence that produced the finding", async () => {
    render([finding()]);

    expect(await screen.findByText("flag{tpyo-in-both}")).toBeInTheDocument();
  });

  it("offers no way to punish anyone — only to dismiss", async () => {
    render([finding()]);
    await screen.findByText("Packet Puzzle", { exact: false });

    const buttons = screen.getAllByRole("button").map((b) => b.textContent?.toLowerCase() ?? "");
    expect(buttons.some((label) => label.includes("looks fine"))).toBe(true);
    expect(
      buttons.some((label) => /ban|disable|penal|remove|punish/.test(label)),
    ).toBe(false);
  });

  it("dismisses a finding", async () => {
    const mock = render([finding()]);

    await userEvent.click(await screen.findByRole("button", { name: /looks fine/i }));

    expect(
      mock.mock.calls.some(([url]) => String(url) === "/api/admin/signals/dismiss"),
    ).toBe(true);
  });

  it("opens a player's timeline from their name", async () => {
    render([finding()], [
      { at: "2026-09-06T12:00:00Z", kind: "attempt", challenge: "Packet Puzzle", detail: "wrong", ip: null },
    ]);

    await userEvent.click(await screen.findByRole("button", { name: "Ada" }));

    const panel = await screen.findByLabelText("Player timeline");
    expect(within(panel).getByText(/everything they did/i)).toBeInTheDocument();
    expect(within(panel).getByText("wrong")).toBeInTheDocument();
  });

  it("says plainly when a player has done nothing", async () => {
    render([finding()], []);

    await userEvent.click(await screen.findByRole("button", { name: "Ada" }));

    expect(await screen.findByText(/nothing recorded for this player/i)).toBeInTheDocument();
  });

  it("says so when there is nothing to review", async () => {
    render([]);

    expect(await screen.findByText(/nothing to review/i)).toBeInTheDocument();
  });
});
