import { api } from "./client";

/** One condition on a locked room or zone (spec 017). `description` is rendered
 *  server-side so the client needs no per-type branch. */
export interface UnlockRequirement {
  type: string;
  met: boolean;
  description: string;
  challenge_id: string | null;
  title: string | null;
  skill_id: string | null;
  skill_name: string | null;
  category_id: string | null;
  category_name: string | null;
  threshold: number | null;
  progress: number | null;
}

export type RoomState = "cleared" | "open" | "shut";

export interface Room {
  challenge_id: string;
  title: string;
  zone_id: string;
  x: number;
  y: number;
  state: RoomState;
  value: number;
  solved: boolean;
  unlock_requirements: UnlockRequirement[];
}

export interface Zone {
  id: string;
  name: string;
  display_order: number;
  locked: boolean;
  unlock_requirements: UnlockRequirement[];
  cleared: number;
  total: number;
}

export interface Edge {
  from_challenge_id: string;
  to_challenge_id: string;
}

export interface DungeonMap {
  /** Dim locked zones. Presentation only — the same rooms come back either way. */
  fog_of_war: boolean;
  zones: Zone[];
  rooms: Room[];
  edges: Edge[];
}

export const getMap = () => api.get<DungeonMap>("/map");
