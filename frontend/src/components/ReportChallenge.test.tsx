import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import ReportChallenge from "./ReportChallenge";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function render() {
  const mock = stubFetch((path, init) => {
    if (path.endsWith("/auth/me")) return { status: 200, body: me() };
    if (init?.method === "POST") {
      return {
        status: 201,
        body: {
          id: "r1",
          challenge_id: "c1",
          challenge_title: null,
          user_id: "u1",
          reporter_name: "Grix",
          message: "The download is corrupt.",
          status: "open",
          resolution_note: null,
          created_at: "2026-09-06T12:00:00Z",
        },
      };
    }
    return { status: 200, body: {} };
  });
  renderApp(<ReportChallenge challengeId="c1" />);
  return mock;
}

describe("ReportChallenge", () => {
  it("stays out of the way until asked for", async () => {
    // Not an alternative to trying; a prominent button invites complaints.
    render();

    expect(
      await screen.findByRole("button", { name: /something's wrong/i }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/what's wrong/i)).not.toBeInTheDocument();
  });

  it("sends a report and confirms it", async () => {
    const mock = render();

    await userEvent.click(await screen.findByRole("button", { name: /something's wrong/i }));
    await userEvent.type(screen.getByLabelText(/what's wrong/i), "The download is corrupt.");
    await userEvent.click(screen.getByRole("button", { name: /send report/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(/an organiser will take a look/i);
    expect(
      mock.mock.calls.some(([url]) => String(url) === "/api/challenges/c1/report"),
    ).toBe(true);
  });

  it("will not send an empty complaint", async () => {
    render();

    await userEvent.click(await screen.findByRole("button", { name: /something's wrong/i }));

    expect(screen.getByRole("button", { name: /send report/i })).toBeDisabled();
  });

  it("can be backed out of", async () => {
    render();

    await userEvent.click(await screen.findByRole("button", { name: /something's wrong/i }));
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));

    expect(screen.getByRole("button", { name: /something's wrong/i })).toBeInTheDocument();
  });
});
