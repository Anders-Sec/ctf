import { api } from "./client";

/**
 * The eight axes a portrait is built from (spec 074 §2).
 *
 * Note what is not in this file: prompt text. The client sends **keys**; the
 * server owns the fragments and the assembly. That is what makes "players
 * cannot write prompts" structural rather than a promise.
 */
export type TraitAxis =
  | "ancestry"
  | "presentation"
  | "class_look"
  | "garb"
  | "expression"
  | "palette"
  | "art_style";

export interface TraitOption {
  key: string;
  label: string;
}

export interface Axis {
  axis: TraitAxis;
  options: TraitOption[];
}

export interface Builder {
  /** False when the host is off, unconfigured, or its breaker is open. */
  available: boolean;
  /** Null means unlimited — an admin, who is exempt from the budget. */
  remaining: number | null;
  candidates_per_job: number;
  /** The player's real class, pre-selected. */
  default_class_look: string | null;
  /** Why the Class axis is empty, when it is. */
  class_locked_note: string | null;
  axes: Axis[];
}

export type JobState = "queued" | "running" | "done" | "failed";

export interface Candidate {
  id: string;
  seed: number;
}

export interface Job {
  id: string;
  state: JobState;
  error: string | null;
  candidates: Candidate[];
  /** Which one is currently the avatar. The rest stay selectable. */
  chosen_candidate_id: string | null;
}

/** Human words for each axis. The server sends keys; naming is a UI decision. */
export const AXIS_LABEL: Record<TraitAxis, string> = {
  ancestry: "Ancestry",
  presentation: "Presentation",
  class_look: "Class",
  garb: "Clothing",
  expression: "Expression",
  palette: "Colours",
  art_style: "Style",
};

export const getBuilder = () => api.get<Builder>("/portraits/builder");

export const startJob = (traits: Record<string, string>) =>
  api.post<Job>("/portraits/jobs", { traits });

export const listJobs = () => api.get<Job[]>("/portraits/jobs");

export const chooseCandidate = (candidateId: string) =>
  api.post<Job>(`/portraits/candidates/${candidateId}/choose`);

export const candidateImageUrl = (candidateId: string) =>
  `/api/portraits/candidates/${candidateId}/image`;
