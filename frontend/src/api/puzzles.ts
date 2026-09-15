import { api } from "./client";

/**
 * Daily puzzles (spec 044).
 *
 * The `puzzle` payload is typed per kind here, but note what the types are
 * *for*: they describe the answer-free projection the server chose to send. They
 * are not a contract the client enforces — nothing in this file could hide an
 * answer that the server had put in the payload, which is precisely why the
 * server never puts one there until the session is over.
 */

export type PuzzleKind = "wordle" | "connections" | "crossword";
export type PuzzleStatus = "in_progress" | "solved" | "failed";

/** Per-letter verdict on a Wordle guess. */
export type LetterVerdict = "exact" | "present" | "absent";

export interface WordleView {
  length: number;
  max_guesses: number;
  guesses: { guess: string; verdicts: LetterVerdict[] }[];
  guesses_remaining: number;
  /** Only once the session is over, and only if the puzzle allows it. */
  answer?: string;
}

export interface ConnectionsGroup {
  name: string;
  level: number;
  members: string[];
}

export interface ConnectionsView {
  /** Still in play, in a stable per-session order. Solved tiles leave the pool. */
  tiles: string[];
  solved_groups: ConnectionsGroup[];
  mistakes: number;
  max_mistakes: number;
  mistakes_remaining: number;
  /** Every group, once the session is over. */
  groups?: ConnectionsGroup[];
}

export interface CrosswordClue {
  number: number;
  direction: "across" | "down";
  row: number;
  col: number;
  length: number;
  clue: string;
}

export interface CrosswordView {
  width: number;
  height: number;
  blocks: [number, number][];
  numbers: { row: number; col: number; number: number }[];
  clues: CrosswordClue[];
  /** What this player has typed. `"#"` marks a block. */
  letters: string[][];
  /** Cells the last check found wrong — marked, never corrected. */
  wrong: [number, number][];
  checks: number;
  max_checks: number;
  checks_remaining: number;
  solution?: string[][];
  answers?: { number: number; direction: string; answer: string }[];
}

export type PuzzleView = WordleView | ConnectionsView | CrosswordView;

export interface PuzzleState {
  kind: PuzzleKind;
  puzzle: PuzzleView;
  /** Null before the first move — looking is not playing. */
  status: PuzzleStatus | null;
  moves_used: number;
  solved: boolean;
  /** What the move just played told the player. Null on a plain read. */
  feedback: PuzzleFeedback | null;
  xp_awarded: number;
}

export interface PuzzleFeedback {
  /** Connections. */
  result?: "correct" | "one_away" | "wrong" | "repeat";
  group?: ConnectionsGroup;
  mistakes_remaining?: number;
  /** Wordle. */
  verdicts?: LetterVerdict[];
  guess?: string;
  /** Crossword. */
  wrong?: [number, number][];
  complete?: boolean;
  checks_remaining?: number;
}

export type PuzzleMove =
  | { guess: string }
  | { members: string[] }
  | { grid: string[][] };

export const getPuzzle = (challengeId: string) =>
  api.get<PuzzleState>(`/challenges/${challengeId}/puzzle`);

export const playMove = (challengeId: string, move: PuzzleMove) =>
  api.post<PuzzleState>(`/challenges/${challengeId}/puzzle/move`, { move });

/** Crossword typing. Evaluates nothing and consumes no check. */
export const savePuzzle = (challengeId: string, grid: string[][]) =>
  api.post<PuzzleState>(`/challenges/${challengeId}/puzzle/save`, { grid });

export const KIND_LABEL: Record<PuzzleKind, string> = {
  wordle: "Wordle",
  connections: "Connections",
  crossword: "Crossword",
};
