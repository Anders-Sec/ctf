import type { BossTier } from "./bosses";
import { api } from "./client";
import type { PuzzleKind } from "./puzzles";
import type {
  Artifact,
  Category,
  ChallengeState,
  Difficulty,
  MatchType,
} from "./challenges";

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
  /** After decay. `initial_points` is the number an admin set. */
  current_value: number;
  initial_points: number;
  boss_tier: BossTier | null;
  ai_ladder_level: number | null;
  has_container: boolean;
  /** A zero is the signal — see spec 041. */
  answer_count: number;
  hint_count: number;
  skill_count: number;
  prerequisite_count: number;
}

/** The canned "what is not finished" queries (spec 041 §4). */
export type Problem =
  | "no_flag"
  | "no_skills"
  | "no_description"
  | "no_hints"
  | "draft"
  | "zone_has_no_boss"
  | "xp_differs_from_difficulty";

export type ChallengeSort =
  | "title"
  | "xp"
  | "difficulty"
  | "solves"
  | "state";

export interface ChallengeFilters {
  search?: string;
  category_id?: string;
  state?: ChallengeState;
  difficulty?: Difficulty;
  boss_tier?: BossTier;
  is_boss?: boolean;
  has_container?: boolean;
  problem?: Problem;
  sort?: ChallengeSort;
}

/** A zone's header row: how much exists, what it is worth, has it a boss. */
export interface ZoneSummary {
  category_id: string;
  name: string;
  slug: string;
  display_order: number;
  challenge_count: number;
  total_xp: number;
  boss_challenge_id: string | null;
  boss_tier: BossTier | null;
  draft_count: number;
  published_count: number;
}

export type BulkAction =
  | "set_state"
  | "set_difficulty"
  | "set_xp"
  | "add_skills"
  | "remove_skills"
  | "set_release_at"
  | "delete";

export interface BulkItemResult {
  challenge_id: string;
  ok: boolean;
  reason: string | null;
}

export interface BulkResult {
  succeeded: number;
  failed: number;
  results: BulkItemResult[];
  /** Zones pruned because their last challenge left (spec 013). */
  categories_deleted: string[];
}

export interface EmptiedZone {
  category_id: string;
  name: string;
  skills_orphaned: number;
}

export interface DeletePreview {
  deletable: number;
  blocked: BulkItemResult[];
  zones_emptied: EmptiedZone[];
}

export interface AdminChallengeDetail {
  id: string;
  /** Null when this challenge is not a boss. */
  boss_tier?: BossTier | null;
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
  container_template_id: string | null;
  prerequisites: { challenge_id: string; title: string }[];
  /** The attached puzzle, answers and all (spec 044). Null for an ordinary
   *  challenge — which is nearly all of them. */
  puzzle: AdminPuzzle | null;
  created_at: string;
}

export interface AdminPuzzle {
  kind: PuzzleKind;
  /** As stored: normalised by the engine, so this is what will be played rather
   *  than what was typed. Contains the answers — admin eyes only. */
  config: Record<string, unknown>;
  sessions: number;
  solved: number;
  failed: number;
}

export interface PuzzleValidation {
  kind: PuzzleKind;
  config: Record<string, unknown>;
  /** Advisory, not errors. Things worth knowing before the event rather than
   *  during it. */
  notes: string[];
}

export interface WordleConfig {
  answer: string;
  length: number;
  max_guesses: number;
  extra_words: string[];
  reveal_on_fail: boolean;
}

export interface ConnectionsConfig {
  groups: { name: string; level: number; members: string[] }[];
  max_mistakes: number;
}

export interface CrosswordConfig {
  width: number;
  height: number;
  blocks: [number, number][];
  entries: {
    number: number;
    direction: "across" | "down";
    row: number;
    col: number;
    length: number;
    answer: string;
    clue: string;
  }[];
  max_checks: number;
}

export interface UpdateChallengeInput {
  title?: string;
  slug?: string;
  category?: string;
  body?: string;
  difficulty?: Difficulty;
  /** The XP a solve awards. Difficulty no longer derives it (spec 040). */
  initial_points?: number;
  /** The floor decay stops at. Null resets it to 40% of the XP. */
  minimum_points?: number | null;
  decay_threshold?: number;
  scoring?: "dynamic" | "static";
  decay_basis?: "players" | "teams";
  max_attempts?: number | null;
  release_at?: string | null;
  pre_release_state?: "hidden" | "locked";
  container_template_id?: string | null;
  /** Null clears the boss flag; a tier sets it (spec 031). */
  boss_tier?: BossTier | null;
}

export interface AnswerTestResult {
  correct: boolean;
  matched_answer_id: string | null;
  matched_label: string | null;
  errors: string[];
}

export const listAdminChallenges = (filters: ChallengeFilters = {}) => {
  // Filtering is server-side (spec 041): the useful questions at 242 are
  // set-shaped, and 042's "select all matching" needs the server to decide
  // the set rather than the rendered page.
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "" && value !== null) {
      query.set(key, String(value));
    }
  }
  const suffix = query.toString();
  return api.get<AdminChallengeSummary[]>(
    `/admin/challenges${suffix ? `?${suffix}` : ""}`,
  );
};

export const listZones = () => api.get<ZoneSummary[]>("/admin/zones");

export const bulkEdit = (
  challenge_ids: string[],
  action: BulkAction,
  value?: unknown,
) =>
  api.post<BulkResult>("/admin/challenges/bulk", {
    challenge_ids,
    action,
    value: value ?? null,
  });

export const previewBulkDelete = (challenge_ids: string[]) =>
  api.post<DeletePreview>("/admin/challenges/bulk/preview-delete", {
    challenge_ids,
    action: "delete",
  });

export const getAdminChallenge = (id: string) =>
  api.get<AdminChallengeDetail>(`/admin/challenges/${id}`);

export const createChallenge = (input: {
  title: string;
  slug: string;
  /** Category name, typed on the form. The backend reuses or creates it. */
  category: string;
  body?: string;
  difficulty?: Difficulty;
  /** Omit to take the difficulty's suggestion (spec 040). */
  initial_points?: number;
  minimum_points?: number;
}) => api.post<AdminChallengeDetail>("/admin/challenges", input);

export const setChallengeState = (
  id: string,
  state: ChallengeState,
  reason?: string,
) =>
  api.post<AdminChallengeDetail>(`/admin/challenges/${id}/state`, {
    state,
    reason: reason ?? null,
  });

export const addAnswer = (
  challengeId: string,
  input: {
    match_type: MatchType;
    value: string;
    options?: Record<string, unknown>;
    label?: string;
  },
) => api.post<AdminAnswer>(`/admin/challenges/${challengeId}/answers`, input);

export const deleteAnswer = (challengeId: string, answerId: string) =>
  api.delete<{ message: string }>(
    `/admin/challenges/${challengeId}/answers/${answerId}`,
  );

/** Dry run. Records nothing — the point is to try a pattern before players do. */
export const testAnswer = (challengeId: string, candidate: string) =>
  api.post<AnswerTestResult>(`/admin/challenges/${challengeId}/answers/test`, {
    candidate,
  });

export const listAdminCategories = () => api.get<Category[]>("/categories");

export const updateChallenge = (id: string, input: UpdateChallengeInput) =>
  api.patch<AdminChallengeDetail>(`/admin/challenges/${id}`, input);

export const addPrerequisite = (
  challengeId: string,
  requiredChallengeId: string,
) =>
  api.post<{ challenge_id: string; title: string }[]>(
    `/admin/challenges/${challengeId}/prerequisites`,
    { required_challenge_id: requiredChallengeId },
  );

export const removePrerequisite = (
  challengeId: string,
  requiredChallengeId: string,
) =>
  api.delete<void>(
    `/admin/challenges/${challengeId}/prerequisites/${requiredChallengeId}`,
  );

/** Deletes the challenge, and prunes its category if that leaves it empty. */
export const deleteChallenge = (id: string) =>
  api.delete<{ message: string }>(`/admin/challenges/${id}`);

export const setPuzzle = (
  challengeId: string,
  kind: PuzzleKind,
  config: Record<string, unknown>,
) =>
  api.put<PuzzleValidation>(`/admin/challenges/${challengeId}/puzzle`, {
    kind,
    config,
  });

export const clearPuzzle = (challengeId: string) =>
  api.delete<{ message: string }>(`/admin/challenges/${challengeId}/puzzle`);
