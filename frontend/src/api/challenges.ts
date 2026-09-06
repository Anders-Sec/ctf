import { api } from "./client";

export type Difficulty = "easy" | "medium" | "hard" | "insane";
export type ChallengeState = "draft" | "hidden" | "locked" | "published";
export type MatchType =
  | "exact"
  | "case_insensitive"
  | "regex"
  | "numeric"
  | "set"
  | "any_of";

export interface Category {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  display_order: number;
}

export interface Artifact {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  checksum_sha256: string;
}

export interface ChallengeListItem {
  id: string;
  title: string;
  slug: string;
  category: Category;
  difficulty: Difficulty;
  state: ChallengeState;
  locked: boolean;
  value: number;
  solve_count: number;
  solved: boolean;
  attempts_remaining: number | null;
  max_attempts: number | null;
  release_at: string | null;
}

export interface Hint {
  id: string;
  title: string;
  /** What unlocking costs right now — zero once the challenge is solved. */
  cost: number;
  unlocked: boolean;
  /** False while a prerequisite is unbought or the reveal time has not come. */
  available: boolean;
  /** Null until unlocked. Withheld server-side, like a locked challenge's body. */
  body: string | null;
}

export interface ChallengeDetail extends ChallengeListItem {
  /** Null while locked — the server withholds it rather than trusting us to hide it. */
  body: string | null;
  artifacts: Artifact[];
  hints: Hint[];
}

export interface UnlockHintResult {
  body: string;
  cost_charged: number;
  already_unlocked: boolean;
  new_total: number;
}

export interface SubmitResult {
  correct: boolean;
  already_solved: boolean;
  points_awarded: number;
  attempts_remaining: number | null;
  message: string;
}

export interface SolveSummary {
  challenge_id: string;
  title: string;
  category: string;
  value: number;
  solved_at: string;
}

export interface MyScore {
  total: number;
  solves: SolveSummary[];
}

export const listChallenges = () => api.get<ChallengeListItem[]>("/challenges");
export const getChallenge = (id: string) => api.get<ChallengeDetail>(`/challenges/${id}`);
export const submitAnswer = (id: string, answer: string) =>
  api.post<SubmitResult>(`/challenges/${id}/submit`, { answer });
export const getMyScore = () => api.get<MyScore>("/me/score");
export const unlockHint = (challengeId: string, hintId: string) =>
  api.post<UnlockHintResult>(`/challenges/${challengeId}/hints/${hintId}/unlock`);
export const artifactUrl = (challengeId: string, artifactId: string) =>
  `/api/challenges/${challengeId}/artifacts/${artifactId}`;
