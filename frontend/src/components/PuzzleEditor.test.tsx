import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import PuzzleEditor from "./PuzzleEditor";
import type { AdminChallengeDetail } from "../api/adminChallenges";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function challenge(overrides: Partial<AdminChallengeDetail> = {}): AdminChallengeDetail {
  return {
    id: "c1",
    title: "Wordle — Day 1",
    slug: "wordle-day-1",
    category: {
      id: "cat1",
      name: "Hacker Game Show",
      slug: "hacker-game-show",
      description: null,
      display_order: 0,
    },
    difficulty: "very_easy",
    state: "draft",
    release_at: null,
    pre_release_state: "hidden",
    initial_points: 50,
    minimum_points: 20,
    decay_threshold: 40,
    scoring: "static",
    decay_basis: "players",
    max_attempts: null,
    solve_count: 0,
    current_value: 50,
    body: "",
    answers: [],
    artifacts: [],
    container_template_id: null,
    prerequisites: [],
    puzzle: null,
    created_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

function serve(handler?: (url: string, init?: RequestInit) => { status: number; body: unknown }) {
  return stubFetch((url, init) => {
    if (url.includes("/api/me")) return { status: 200, body: me() };
    if (handler) return handler(url, init);
    return { status: 200, body: { kind: "wordle", config: {}, notes: [] } };
  });
}

it("refuses to author a puzzle on a challenge that already has flags", async () => {
  // The rule, said where the author is standing rather than as a 409 later.
  serve();

  renderApp(
    <PuzzleEditor
      challenge={challenge({
        answers: [
          {
            id: "a1",
            match_type: "exact",
            value: "flag{x}",
            options: {},
            label: null,
            display_order: 0,
          },
        ],
      })}
      onChanged={() => {}}
    />,
  );

  expect(await screen.findByText(/remove the flags first/i)).toBeInTheDocument();
  expect(screen.queryByLabelText("Game")).not.toBeInTheDocument();
});

it("sends the authored wordle and shows what the server made of it", async () => {
  const fetchMock = serve((url) => {
    if (url.includes("/puzzle")) {
      return {
        status: 200,
        body: {
          kind: "wordle",
          config: { answer: "PROXY", length: 5, max_guesses: 6, extra_words: [] },
          notes: ["1058 words of this length are in the guess list."],
        },
      };
    }
    return { status: 404, body: {} };
  });

  renderApp(<PuzzleEditor challenge={challenge()} onChanged={() => {}} />);

  await userEvent.selectOptions(screen.getByLabelText("Game"), "wordle");
  await userEvent.type(screen.getByLabelText("Answer (five letters)"), "proxy");
  await userEvent.click(screen.getByRole("button", { name: "Save puzzle" }));

  // The advisory note is the point: an author needs to know a Wordle is
  // playable before the event, not during it.
  expect(
    await screen.findByText("1058 words of this length are in the guess list."),
  ).toBeInTheDocument();

  const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/puzzle"));
  const body = JSON.parse(String((call?.[1] as RequestInit).body));
  expect(body.kind).toBe("wordle");
  expect(body.config.answer).toBe("PROXY");
});

it("marks the field the engine objected to", async () => {
  serve((url) =>
    url.includes("/puzzle")
      ? {
          status: 422,
          body: {
            error: {
              code: "invalid_puzzle_config",
              message: "The answer must be 5 letters.",
              details: { field: "answer" },
            },
          },
        }
      : { status: 404, body: {} },
  );

  renderApp(<PuzzleEditor challenge={challenge()} onChanged={() => {}} />);

  await userEvent.selectOptions(screen.getByLabelText("Game"), "wordle");
  await userEvent.type(screen.getByLabelText("Answer (five letters)"), "four");
  await userEvent.click(screen.getByRole("button", { name: "Save puzzle" }));

  expect(await screen.findByText("answer")).toBeInTheDocument();
});

it("offers four groups of four for a connections", async () => {
  serve();

  renderApp(<PuzzleEditor challenge={challenge()} onChanged={() => {}} />);
  await userEvent.selectOptions(screen.getByLabelText("Game"), "connections");

  for (const level of [1, 2, 3, 4]) {
    for (const tile of [1, 2, 3, 4]) {
      expect(screen.getByLabelText(`Level ${level}, tile ${tile}`)).toBeInTheDocument();
    }
  }
});

it("toggles crossword blocks on the grid", async () => {
  const fetchMock = serve((url) =>
    url.includes("/puzzle")
      ? { status: 200, body: { kind: "crossword", config: {}, notes: [] } }
      : { status: 404, body: {} },
  );

  renderApp(<PuzzleEditor challenge={challenge()} onChanged={() => {}} />);
  await userEvent.selectOptions(screen.getByLabelText("Game"), "crossword");

  const cell = screen.getByLabelText("Row 1, column 1");
  expect(cell).toHaveAttribute("aria-pressed", "false");
  await userEvent.click(cell);
  expect(screen.getByLabelText("Row 1, column 1, block")).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  await userEvent.click(screen.getByRole("button", { name: "Save puzzle" }));
  await waitFor(() => {
    const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/puzzle"));
    expect(JSON.parse(String((call?.[1] as RequestInit).body)).config.blocks).toEqual([[0, 0]]);
  });
});

it("warns when a live puzzle has beaten everyone who tried it", async () => {
  // The signal worth surfacing while there is still time to do something.
  serve();

  renderApp(
    <PuzzleEditor
      challenge={challenge({
        puzzle: {
          kind: "wordle",
          config: { answer: "PROXY", length: 5, max_guesses: 6, extra_words: [] },
          sessions: 30,
          solved: 0,
          failed: 12,
        },
      })}
      onChanged={() => {}}
    />,
  );

  expect(await screen.findByText(/Nobody has finished this one/)).toBeInTheDocument();
  expect(screen.getByText(/30 played · 0 solved · 12 lost/)).toBeInTheDocument();
});

it("says how many sessions a removal will take with it", async () => {
  const confirm = vi.fn(() => false);
  vi.stubGlobal("confirm", confirm);
  serve();

  renderApp(
    <PuzzleEditor
      challenge={challenge({
        puzzle: {
          kind: "wordle",
          config: { answer: "PROXY" },
          sessions: 7,
          solved: 3,
          failed: 1,
        },
      })}
      onChanged={() => {}}
    />,
  );

  await userEvent.click(await screen.findByRole("button", { name: "Remove puzzle" }));

  expect(confirm).toHaveBeenCalledWith(expect.stringContaining("7 player session(s)"));
});
