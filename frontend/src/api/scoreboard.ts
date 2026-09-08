import { api } from "./client";

export interface PlayerEntry {
  rank: number;
  user_id: string;
  display_name: string;
  has_avatar: boolean;
  team_id: string | null;
  team_name: string | null;
  score: number;
  level: number;
  solve_count: number;
  last_gain_at: string | null;
}

export interface TeamEntry {
  rank: number;
  team_id: string;
  name: string;
  member_count: number;
  score: number;
  level: number;
  /** Distinct challenges solved by any current member. */
  solve_count: number;
  last_gain_at: string | null;
}

export interface Boards {
  generated_at: string;
  players: PlayerEntry[];
  teams: TeamEntry[];
}

export interface MyStanding {
  rank: number | null;
  score: number;
  level: number;
  player_count: number;
  team_rank: number | null;
  team_score: number | null;
  team_level: number | null;
  team_count: number;
}

export const getPlayerBoard = () =>
  api.get<{ total: number; generated_at: string; entries: PlayerEntry[] }>(
    "/scoreboard/players",
  );

export const getTeamBoard = () =>
  api.get<{ total: number; generated_at: string; entries: TeamEntry[] }>("/scoreboard/teams");

export const getMyStanding = () => api.get<MyStanding>("/scoreboard/me");

/** The socket rides the same origin as the API, so the session cookie goes with it. */
export function scoreboardSocketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/ws/scoreboard`;
}
