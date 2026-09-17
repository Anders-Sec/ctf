import { api } from "./client";

/**
 * The staff board (spec 051 §3).
 *
 * Ranks and totals are the public board's, unchanged. What is added here is the
 * three things the public board deliberately withholds.
 */

export interface AdminBoardRow {
  rank: number;
  score: number;
  level: number;
  solve_count: number;
  /** The tie-break. Two entries on equal points are ordered by who got there first. */
  last_gain_at: string | null;
  /** `score` split; the two always add back to it. */
  solve_points: number;
  adjustment_points: number;
}

export interface AdminPlayerRow extends AdminBoardRow {
  user_id: string;
  display_name: string;
  team_id: string | null;
  team_name: string | null;
}

export interface AdminTeamRow extends AdminBoardRow {
  team_id: string;
  name: string;
  member_count: number;
}

/** Scored, but kept off the public board — disabled, or staff. */
export interface UnrankedRow {
  user_id: string;
  display_name: string;
  solve_points: number;
  adjustment_points: number;
  score: number;
  status: string;
  role: string;
  reason: "disabled" | "staff";
}

export interface AdminBoard {
  generated_at: string;
  server_time: string;
  players: AdminPlayerRow[];
  teams: AdminTeamRow[];
  unranked: UnrankedRow[];
}

export const getAdminBoard = () => api.get<AdminBoard>("/admin/scoreboard");
