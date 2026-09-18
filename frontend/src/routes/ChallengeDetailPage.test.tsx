import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Link, Outlet, Route, Routes } from "react-router-dom";

import ChallengeDetailPage from "./ChallengeDetailPage";
import type { ChallengeDetail } from "../api/challenges";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function detail(overrides: Partial<ChallengeDetail> = {}): ChallengeDetail {
  return {
    id: "c1",
    title: "Packet Puzzle",
    slug: "packet-puzzle",
    category: {
      id: "cat1",
      name: "Forensics",
      slug: "forensics",
      description: null,
      display_order: 0,
    },
    difficulty: "medium",
    state: "published",
    locked: false,
    value: 420,
    solve_count: 3,
    solved: false,
    attempts_remaining: null,
    max_attempts: null,
    release_at: null,
    unlock_requirements: [],
    puzzle_kind: null,
    puzzle_status: null,
    body: "Find the flag in the capture.",
    artifacts: [],
    hints: [],
    has_container: false,
    ...overrides,
  };
}

function render(challenge: ChallengeDetail, submitResult?: Record<string, unknown>) {
  const mock = stubFetch((path, init) => {
    if (path.endsWith("/auth/me")) return { status: 200, body: me() };
    if (init?.method === "POST") {
      return {
        status: 200,
        body: submitResult ?? {
          correct: false,
          already_solved: false,
          points_awarded: 0,
          attempts_remaining: null,
          message: "Not quite. Try again.",
        },
      };
    }
    return { status: 200, body: challenge };
  });

  renderApp(
    <Routes>
      <Route path="/challenges/:challengeId" element={<ChallengeDetailPage />} />
    </Routes>,
    { route: "/challenges/c1" },
  );
  return mock;
}

describe("ChallengeDetailPage", () => {
  it("shows the challenge body and value", async () => {
    render(detail());

    expect(await screen.findByText("Find the flag in the capture.")).toBeInTheDocument();
    expect(screen.getByText(/420 XP/)).toBeInTheDocument();
  });

  it("submits an answer and reports the verdict", async () => {
    const mock = render(detail(), {
      correct: true,
      already_solved: false,
      points_awarded: 420,
      attempts_remaining: null,
      message: "Correct. 420 XP.",
    });

    // paste, not type: userEvent reads {...} as key descriptors and would eat
    // the braces — and pasting is what a player does with a flag anyway.
    await userEvent.click(await screen.findByLabelText(/your answer/i));
    await userEvent.paste("flag{abc}");
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));

    expect(await screen.findByRole("status")).toHaveTextContent("Correct. 420 XP.");

    const submitCall = mock.mock.calls.find(
      ([url]) => String(url) === "/api/challenges/c1/submit",
    );
    expect(submitCall).toBeDefined();
    const init = submitCall![1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ answer: "flag{abc}" }));
  });

  it("reports a wrong answer without discouraging a retry", async () => {
    render(detail());

    await userEvent.type(await screen.findByLabelText(/your answer/i), "nope");
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(/not quite/i);
    // The field stays enabled: a wrong answer is not the end of the attempt.
    expect(screen.getByLabelText(/your answer/i)).toBeEnabled();
  });

  it("will not submit an empty answer", async () => {
    render(detail());
    await screen.findByLabelText(/your answer/i);

    expect(screen.getByRole("button", { name: /submit/i })).toBeDisabled();
  });

  it("says when the challenge is already solved", async () => {
    render(detail({ solved: true }));

    expect(await screen.findByText(/already cleared/i)).toBeInTheDocument();
  });

  it("disables submission once attempts run out", async () => {
    render(detail({ max_attempts: 2, attempts_remaining: 0 }));

    expect(await screen.findByText(/no attempts left/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/your answer/i)).toBeDisabled();
  });

  it("offers downloadable files", async () => {
    render(
      detail({
        artifacts: [
          {
            id: "a1",
            filename: "capture.pcap",
            content_type: "application/vnd.tcpdump.pcap",
            size_bytes: 2048,
            checksum_sha256: "abc",
          },
        ],
      }),
    );

    const link = await screen.findByRole("link", { name: "capture.pcap" });
    expect(link).toHaveAttribute("href", "/api/challenges/c1/artifacts/a1");
  });

  it("explains a 404 as not yet unsealed rather than an error", async () => {
    stubFetch((path) => {
      if (path.endsWith("/auth/me")) return { status: 200, body: me() };
      return { status: 404, body: { error: { code: "not_found", message: "No such challenge." } } };
    });
    renderApp(
      <Routes>
        <Route path="/challenges/:challengeId" element={<ChallengeDetailPage />} />
      </Routes>,
      { route: "/challenges/missing" },
    );

    expect(await screen.findByText(/no such challenge/i)).toBeInTheDocument();
    expect(screen.getByText(/may not have been unsealed/i)).toBeInTheDocument();
  });
});

describe("focus (spec 071)", () => {
  it("moves focus into the overlay when it opens", async () => {
    render(detail());
    const panel = await screen.findByRole("dialog", { name: /packet puzzle/i });

    expect(panel).toContainElement(document.activeElement as HTMLElement);
  });

  it("keeps Tab inside the overlay rather than in the board behind it", async () => {
    render(detail());
    const panel = await screen.findByRole("dialog", { name: /packet puzzle/i });

    // The complaint 071 was written for: the board underneath is still mounted
    // and still focusable, under a sheet that says it is not.
    for (let index = 0; index < 8; index += 1) {
      await userEvent.tab();
      expect(panel).toContainElement(document.activeElement as HTMLElement);
    }
  });

  it("returns focus to the row that opened it", async () => {
    // Spec 071 §8.1 asked whether to restore to the row or to the board
    // container. Capturing whatever had focus at open time answers it without
    // any per-caller code: the row is what had it.
    stubFetch((path) => {
      if (path.endsWith("/auth/me")) return { status: 200, body: me() };
      return { status: 200, body: detail() };
    });

    // Nested exactly as App.tsx nests them: the board stays mounted behind the
    // overlay, which is what lets the row still be there to focus afterwards.
    renderApp(
      <Routes>
        <Route
          path="/challenges"
          element={
            <>
              <Link to="/challenges/c1">Packet Puzzle</Link>
              <Outlet />
            </>
          }
        >
          <Route path=":challengeId" element={<ChallengeDetailPage />} />
        </Route>
      </Routes>,
      { route: "/challenges" },
    );

    const row = await screen.findByRole("link", { name: "Packet Puzzle" });
    await userEvent.click(row);
    await screen.findByRole("dialog", { name: /packet puzzle/i });

    await userEvent.keyboard("{Escape}");

    expect(await screen.findByRole("link", { name: "Packet Puzzle" })).toHaveFocus();
  });
});
