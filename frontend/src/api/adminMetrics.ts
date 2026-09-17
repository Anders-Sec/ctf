import { api } from "./client";

/** Event-operations metrics (spec 050). */

export interface Pulse {
  window: string;
  solves: number;
  solves_previous: number;
  solves_per_hour: number;
  /** The best early warning: it climbs before solves fall. */
  attempts_per_solve: number;
  wrong_attempts: number;
  active_players: number;
  approved_players: number;
  participation: number;
  hints_unlocked: number;
  first_time_solvers: number;
  generated_at: string;
}

export interface ChallengeMetric {
  challenge_id: string;
  title: string;
  zone: string | null;
  difficulty: string;
  state: string;
  attempts: number;
  solves: number;
  attempts_per_solve: number;
  /** Null below the attempt floor — a multiple from three attempts is a lie. */
  vs_difficulty: number | null;
  hint_uptake: number;
  /** A rate. The strings and distances stay on the server: a wrong submission
   *  is as good as a hint. */
  near_miss_rate: number;
}

export interface StalledPlayer {
  user_id: string;
  display_name: string;
  solves: number;
  xp: number;
  level: number;
  last_solve_at: string | null;
  /** Distinguishes stopped playing from stuck and trying. */
  last_submission_at: string | null;
  current_wall: string | null;
  hints_used: number;
}

export interface Progression {
  levels: { level: number; players: number }[];
  zone_spread: { zone: string; players: number }[];
  category_health: {
    zone: string;
    attempts: number;
    solves: number;
    attempts_per_solve: number;
  }[];
  hints: { unlocked: number; players_using: number; hints_per_solve: number };
  generated_at: string;
}

export const getPulse = (window: string) =>
  api.get<Pulse>(`/admin/metrics/pulse?window=${window}`);

export const getChallengeMetrics = (window: string) =>
  api.get<{ window: string; challenges: ChallengeMetric[]; generated_at: string }>(
    `/admin/metrics/challenges?window=${window}`,
  );

export const getPlayerMetrics = (filter: string) =>
  api.get<{ filter: string; players: StalledPlayer[]; generated_at: string }>(
    `/admin/metrics/players?filter=${filter}`,
  );

export const getProgression = () => api.get<Progression>("/admin/metrics/progression");
