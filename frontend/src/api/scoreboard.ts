import { api } from "./client";

/**
 * The boards (spec 005, rebuilt by 059).
 *
 * **Neither entry has a `score`.** XP still orders both boards server-side; it
 * is not sent, and adding it back here is how it ends up rendered. The one place
 * XP belongs is the player's own character sheet.
 */

export type BossTier =
  | "neighborhood"
  | "borough"
  | "city"
  | "province"
  | "country"
  | "floor";

/** One boss kill, identified by the challenge's slug (spec 059 §3). */
export interface BossStar {
  slug: string;
  tier: BossTier;
  /** 1 (Neighborhood) to 6 (Floor), so a run orders without the names. */
  level: number;
  /** For the hover. Colour carries the tier; this carries which boss. */
  title: string;
}

export interface PlayerEntry {
  /** Shared on a tie, so a board can show two third places. */
  rank: number;
  user_id: string;
  display_name: string;
  has_avatar: boolean;
  team_id: string | null;
  team_name: string | null;
  level: number;
  solve_count: number;
  last_gain_at: string | null;
  /** This player's own kills — never their party's. */
  stars: BossStar[];
  /** The worn loot title (038) and the class (016/024). Both cosmetic. */
  title: string | null;
  class_name: string | null;
  class_rarity: string | null;
}

export interface TeamEntry {
  rank: number;
  team_id: string;
  name: string;
  member_count: number;
  level: number;
  /** Distinct challenges solved by any current member. */
  solve_count: number;
  last_gain_at: string | null;
  /** The union across current members, deduplicated by slug. */
  stars: BossStar[];
}

export interface Boards {
  generated_at: string;
  players: PlayerEntry[];
  teams: TeamEntry[];
}

export interface MyStanding {
  rank: number | null;
  level: number;
  player_count: number;
  team_rank: number | null;
  team_level: number | null;
  team_count: number;
}

export interface PartyMember {
  user_id: string;
  display_name: string;
  has_avatar: boolean;
  level: number;
  class_name: string | null;
  class_rarity: string | null;
}

/** Who a party is (spec 059 §5). No XP, member XP included. */
export interface PartyPanel {
  team_id: string;
  name: string;
  rank: number;
  level: number;
  member_count: number;
  solve_count: number;
  achievement_count: number;
  stars: BossStar[];
  founded_at: string;
  members: PartyMember[];
}

/**
 * All the rows in one request.
 *
 * The top-ten framing, the search and "show all" are client-side on a payload
 * the server already computes whole, so paging it would mean asking for
 * something it has already sent (spec 059 §4). 500 is the endpoint's ceiling.
 */
const WHOLE_BOARD = "?limit=500";

export const getPlayerBoard = () =>
  api.get<{ total: number; generated_at: string; entries: PlayerEntry[] }>(
    `/scoreboard/players${WHOLE_BOARD}`,
  );

export const getTeamBoard = () =>
  api.get<{ total: number; generated_at: string; entries: TeamEntry[] }>(
    `/scoreboard/teams${WHOLE_BOARD}`,
  );

export const getMyStanding = () => api.get<MyStanding>("/scoreboard/me");

export const getPartyPanel = (teamId: string) =>
  api.get<PartyPanel>(`/scoreboard/teams/${teamId}`);

/** The socket rides the same origin as the API, so the session cookie goes with it. */
export function scoreboardSocketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/ws/scoreboard`;
}
