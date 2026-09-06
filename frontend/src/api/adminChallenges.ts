import { api } from "./client";
import type { Artifact, Category, ChallengeState, Difficulty, MatchType } from "./challenges";

export interface AdminAnswer {
  id: string;
  match_type: MatchType;
  /** Returned in full: you cannot debug a challenge nobody solves without it. */
  value: string;
  options: Record<string, unknown>;
  label: string | null;
  display_order: number;
}

export interface AdminChallengeSummary {
  id: string;
  title: string;
  slug: string;
  category: Category;
  difficulty: Difficulty;
  state: ChallengeState;
  effective_state: ChallengeState;
  release_at: string | null;
  solve_count: number;
  current_value: number;
  answer_count: number;
}

export interface AdminChallengeDetail {
  id: string;
  title: string;
  slug: string;
  category: Category;
  difficulty: Difficulty;
  state: ChallengeState;
  release_at: string | null;
  pre_release_state: "hidden" | "locked";
  initial_points: number;
  minimum_points: number;
  decay_threshold: number;
  scoring: "dynamic" | "static";
  decay_basis: "players" | "teams";
  max_attempts: number | null;
  solve_count: number;
  current_value: number;
  body: string;
  answers: AdminAnswer[];
  artifacts: Artifact[];
  created_at: string;
}

export interface AnswerTestResult {
  correct: boolean;
  matched_answer_id: string | null;
  matched_label: string | null;
  errors: string[];
}

export const listAdminChallenges = () => api.get<AdminChallengeSummary[]>("/admin/challenges");

export const getAdminChallenge = (id: string) =>
  api.get<AdminChallengeDetail>(`/admin/challenges/${id}`);

export const createChallenge = (input: {
  title: string;
  slug: string;
  category_id: string;
  body?: string;
  difficulty?: Difficulty;
  initial_points?: number;
}) => api.post<AdminChallengeDetail>("/admin/challenges", input);

export const setChallengeState = (id: string, state: ChallengeState, reason?: string) =>
  api.post<AdminChallengeDetail>(`/admin/challenges/${id}/state`, { state, reason: reason ?? null });

export const addAnswer = (
  challengeId: string,
  input: { match_type: MatchType; value: string; options?: Record<string, unknown>; label?: string },
) => api.post<AdminAnswer>(`/admin/challenges/${challengeId}/answers`, input);

export const deleteAnswer = (challengeId: string, answerId: string) =>
  api.delete<{ message: string }>(`/admin/challenges/${challengeId}/answers/${answerId}`);

/** Dry run. Records nothing — the point is to try a pattern before players do. */
export const testAnswer = (challengeId: string, candidate: string) =>
  api.post<AnswerTestResult>(`/admin/challenges/${challengeId}/answers/test`, { candidate });

export const listAdminCategories = () => api.get<Category[]>("/categories");
