import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import PuzzlePanel from "./PuzzlePanel";
import type { PuzzleState } from "../../api/puzzles";
import { me, renderApp, stubFetch } from "../../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

const CHALLENGE = "c1";

function wordle(overrides: Partial<PuzzleState> = {}): PuzzleState {
  return {
    kind: "wordle",
    puzzle: { length: 5, max_guesses: 6, guesses: [], guesses_remaining: 6 },
    status: null,
    moves_used: 0,
    solved: false,
    feedback: null,
    xp_awarded: 0,
    ...overrides,
  };
}

function connections(overrides: Partial<PuzzleState> = {}): PuzzleState {
  return {
    kind: "connections",
    puzzle: {
      tiles: ["22", "80", "443", "3389", "MD5", "SHA1", "BCRYPT", "ARGON2"],
      solved_groups: [],
      mistakes: 0,
      max_mistakes: 4,
      mistakes_remaining: 4,
    },
    status: null,
    moves_used: 0,
    solved: false,
    feedback: null,
    xp_awarded: 0,
    ...overrides,
  };
}

function crossword(overrides: Partial<PuzzleState> = {}): PuzzleState {
  return {
    kind: "crossword",
    puzzle: {
      width: 2,
      height: 1,
      blocks: [],
      numbers: [{ row: 0, col: 0, number: 1 }],
      clues: [
        { number: 1, direction: "across", row: 0, col: 0, length: 2, clue: "Feline, briefly" },
      ],
      letters: [["", ""]],
      wrong: [],
      checks: 0,
      max_checks: 3,
      checks_remaining: 3,
    },
    status: null,
    moves_used: 0,
    solved: false,
    feedback: null,
    xp_awarded: 0,
    ...overrides,
  };
}

/** Serve `/me` plus the puzzle, and route moves to `onMove`. */
function serve(state: PuzzleState, onMove?: (body: unknown) => { status: number; body: unknown }) {
  return stubFetch((url, init) => {
    if (url.includes("/api/me")) return { status: 200, body: me() };
    if (url.includes("/puzzle/move")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      return onMove ? onMove(body) : { status: 200, body: state };
    }
    if (url.includes("/puzzle/save")) return { status: 200, body: state };
    if (url.includes("/puzzle")) return { status: 200, body: state };
    return { status: 404, body: { error: { code: "not_found", message: "no" } } };
  });
}

it("plays a wordle guess through the on-screen keyboard", async () => {
  const played = wordle({
    puzzle: {
      length: 5,
      max_guesses: 6,
      guesses: [
        { guess: "AUDIT", verdicts: ["absent", "absent", "absent", "present", "absent"] },
      ],
      guesses_remaining: 5,
    },
    status: "in_progress",
    moves_used: 1,
  });
  const fetchMock = serve(wordle(), () => ({ status: 200, body: played }));

  renderApp(<PuzzlePanel challengeId={CHALLENGE} />);
  await screen.findByRole("group", { name: /wordle/i });

  for (const letter of "AUDIT") {
    await userEvent.click(screen.getByRole("button", { name: letter }));
  }
  await userEvent.click(screen.getByRole("button", { name: "Enter" }));

  await waitFor(() => expect(screen.getByText("5 guesses left")).toBeInTheDocument());
  const move = fetchMock.mock.calls.find(([url]) => String(url).includes("/move"));
  expect(JSON.parse(String((move?.[1] as RequestInit).body))).toEqual({
    move: { guess: "AUDIT" },
  });
});

it("spells out each letter's verdict rather than relying on colour", async () => {
  // Around 1 in 12 men cannot tell the green from the amber.
  serve(
    wordle({
      puzzle: {
        length: 5,
        max_guesses: 6,
        guesses: [
          { guess: "AUDIT", verdicts: ["exact", "present", "absent", "absent", "absent"] },
        ],
        guesses_remaining: 5,
      },
      status: "in_progress",
    }),
  );

  renderApp(<PuzzlePanel challengeId={CHALLENGE} />);

  // The tile is named by its position, so it is never confused with the
  // keyboard key for the same letter — which carries the same hint.
  expect(
    await screen.findByLabelText("Guess 1, letter 1: A, right letter, right place"),
  ).toBeInTheDocument();
  expect(
    screen.getByLabelText("Guess 1, letter 2: U, right letter, wrong place"),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Guess 1, letter 3: D, not in the word")).toBeInTheDocument();
  // And the key still announces what it knows.
  expect(screen.getByRole("button", { name: "A, right letter, right place" })).toBeInTheDocument();
});

it("shows a refused guess as a note, not an error, and keeps the board", async () => {
  serve(wordle(), () => ({
    status: 422,
    body: { error: { code: "unknown_word", message: "Not in the word list." } },
  }));

  renderApp(<PuzzlePanel challengeId={CHALLENGE} />);
  await screen.findByRole("group", { name: /wordle/i });

  for (const letter of "ZZZZZ") {
    await userEvent.click(screen.getByRole("button", { name: letter }));
  }
  await userEvent.click(screen.getByRole("button", { name: "Enter" }));

  expect(await screen.findByText("Not in the word list.")).toBeInTheDocument();
  // Nothing was spent: still six guesses.
  expect(screen.getByText("6 guesses left")).toBeInTheDocument();
});

it("reveals the answer once the day is lost", async () => {
  serve(
    wordle({
      puzzle: { length: 5, max_guesses: 1, guesses: [], guesses_remaining: 0, answer: "PROXY" },
      status: "failed",
    }),
  );

  renderApp(<PuzzlePanel challengeId={CHALLENGE} />);

  expect(await screen.findByText(/It was PROXY/)).toBeInTheDocument();
  expect(screen.getByText("Out of luck today")).toBeInTheDocument();
  // No way back in.
  expect(screen.queryByRole("button", { name: "Enter" })).not.toBeInTheDocument();
});

it("announces a solve with the XP it banked", async () => {
  serve(wordle({ status: "solved", solved: true, xp_awarded: 150 }));

  renderApp(<PuzzlePanel challengeId={CHALLENGE} />);

  expect(await screen.findByText("Solved · 150 XP")).toBeInTheDocument();
});

it("submits four connections tiles and lets you deselect for free", async () => {
  const fetchMock = serve(connections());

  renderApp(<PuzzlePanel challengeId={CHALLENGE} />);
  await screen.findByRole("button", { name: "22" });

  await userEvent.click(screen.getByRole("button", { name: "22" }));
  await userEvent.click(screen.getByRole("button", { name: "80" }));
  expect(screen.getByRole("button", { name: "22" })).toHaveAttribute("aria-pressed", "true");

  // Submit stays disabled until there are four, and deselecting costs nothing.
  expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Deselect" }));
  expect(screen.getByRole("button", { name: "22" })).toHaveAttribute("aria-pressed", "false");
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/move"))).toHaveLength(0);

  for (const tile of ["22", "80", "443", "3389"]) {
    await userEvent.click(screen.getByRole("button", { name: tile }));
  }
  await userEvent.click(screen.getByRole("button", { name: "Submit" }));

  await waitFor(() => {
    const move = fetchMock.mock.calls.find(([url]) => String(url).includes("/move"));
    expect(JSON.parse(String((move?.[1] as RequestInit).body)).move.members).toEqual([
      "22",
      "80",
      "443",
      "3389",
    ]);
  });
});

it("says one away when a connections guess was close", async () => {
  serve(connections(), () => ({
    status: 200,
    body: connections({
      status: "in_progress",
      feedback: { result: "one_away", mistakes_remaining: 3 },
      puzzle: {
        tiles: ["22", "80", "443", "3389", "MD5", "SHA1", "BCRYPT", "ARGON2"],
        solved_groups: [],
        mistakes: 1,
        max_mistakes: 4,
        mistakes_remaining: 3,
      },
    }),
  }));

  renderApp(<PuzzlePanel challengeId={CHALLENGE} />);
  await screen.findByRole("button", { name: "22" });
  for (const tile of ["22", "80", "443", "MD5"]) {
    await userEvent.click(screen.getByRole("button", { name: tile }));
  }
  await userEvent.click(screen.getByRole("button", { name: "Submit" }));

  expect(await screen.findByText("One away…")).toBeInTheDocument();
  expect(screen.getByText("3 mistakes left")).toBeInTheDocument();
});

it("keeps crossword typing in local storage as it is typed", async () => {
  serve(crossword());

  renderApp(<PuzzlePanel challengeId={CHALLENGE} />);
  const cell = await screen.findByLabelText("Row 1, column 1");

  await userEvent.type(cell, "C");

  await waitFor(() => {
    const stored = JSON.parse(localStorage.getItem(`ctf.crossword.${CHALLENGE}`) ?? "{}");
    expect(stored.grid[0][0]).toBe("C");
  });
});

it("resumes a crossword from local storage when the server's copy is emptier", async () => {
  // The case this exists for: typed on one device, opened on the same browser
  // again before anything was flushed.
  localStorage.setItem(
    `ctf.crossword.${CHALLENGE}`,
    JSON.stringify({ grid: [["C", "A"]], saved_at: Date.now() }),
  );
  serve(crossword());

  renderApp(<PuzzlePanel challengeId={CHALLENGE} />);

  expect(await screen.findByLabelText("Row 1, column 1")).toHaveValue("C");
  expect(screen.getByLabelText("Row 1, column 2")).toHaveValue("A");
});

it("marks the cells a check found wrong without correcting them", async () => {
  serve(
    crossword({
      status: "in_progress",
      puzzle: {
        ...(crossword().puzzle as never as Record<string, unknown>),
        letters: [["X", "A"]],
        wrong: [[0, 0]],
        checks: 1,
        checks_remaining: 2,
      } as never,
    }),
  );

  renderApp(<PuzzlePanel challengeId={CHALLENGE} />);

  const cell = await screen.findByLabelText("Row 1, column 1, wrong");
  // Marked, and the player's own letter is still there.
  expect(cell).toHaveValue("X");
  expect(screen.getByText(/2 checks left/)).toBeInTheDocument();
});

it("flushes the crossword to the server when the panel goes away", async () => {
  const fetchMock = serve(crossword());
  const { unmount } = renderApp(<PuzzlePanel challengeId={CHALLENGE} />);
  await screen.findByLabelText("Row 1, column 1");

  unmount();

  await waitFor(() =>
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/puzzle/save"))).toBe(true),
  );
});

it("offers no check button once the crossword is over", async () => {
  serve(crossword({ status: "solved", solved: true, xp_awarded: 150 }));

  renderApp(<PuzzlePanel challengeId={CHALLENGE} />);

  expect(await screen.findByText("Solved · 150 XP")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Check" })).not.toBeInTheDocument();
  expect(within(screen.getByRole("grid")).getByLabelText("Row 1, column 1")).toBeDisabled();
});
