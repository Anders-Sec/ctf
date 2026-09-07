import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminAssistantPage from "./AdminAssistantPage";
import type { AssistantFinding } from "../api/assistantAdmin";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function finding(overrides: Partial<AssistantFinding> = {}): AssistantFinding {
  return {
    id: "f1",
    created_at: "2026-09-07T10:00:00Z",
    layer: "integrity",
    rule: "answer_verbatim",
    severity: "high",
    action: "deflected",
    player_name: "Mira",
    challenge_id: "c1",
    question: "what's the flag?",
    reply: "It is flag{withheld_secret}",
    detail: {},
    ...overrides,
  };
}

function render(findings: AssistantFinding[]) {
  const mock = stubFetch((path) => {
    if (path.endsWith("/auth/me")) {
      return { status: 200, body: me({ user: { ...me().user, role: "organizer" } }) };
    }
    if (path.includes("/admin/assistant/findings")) {
      return { status: 200, body: { findings, total: findings.length } };
    }
    return { status: 200, body: {} };
  });
  renderApp(<AdminAssistantPage />);
  return mock;
}

describe("AdminAssistantPage", () => {
  it("shows a flagged exchange, withheld reply and all", async () => {
    render([finding()]);

    expect(await screen.findByText(/reply contained a real answer/i)).toBeInTheDocument();
    expect(screen.getByText("what's the flag?")).toBeInTheDocument();
    // The reviewer is shown the text the player never saw.
    expect(screen.getByText("It is flag{withheld_secret}")).toBeInTheDocument();
    expect(screen.getByText(/withheld reply/i)).toBeInTheDocument();
  });

  it("frames flags as review, not accusation", async () => {
    render([finding()]);

    expect(
      await screen.findByText(/asking the system ai for the flag is a joke/i),
    ).toBeInTheDocument();
  });

  it("filters by layer", async () => {
    const fetchMock = render([finding()]);
    await screen.findByText(/reply contained a real answer/i);

    await userEvent.click(screen.getByRole("button", { name: "Safety" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([path]) => String(path).includes("layer=safety")),
      ).toBe(true);
    });
  });

  it("says so when nothing is flagged", async () => {
    render([]);

    expect(await screen.findByText(/nothing flagged/i)).toBeInTheDocument();
  });
});
