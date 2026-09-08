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

export interface Zone {
  id: string;
  name: string;
  /** Matches the artwork filename — how a tile is wired to its zone. */
  slug: string;
  ability: string;
  display_order: number;
  x: number;
  y: number;
  locked: boolean;
  unlock_requirements: UnlockRequirement[];
  cleared: number;
  total: number;
}

/** A corridor: `from_zone_id` is what opens `to_zone_id`. */
export interface Edge {
  from_zone_id: string;
  to_zone_id: string;
}

export interface DungeonMap {
  /** Dim locked zones. Presentation only — the same zones come back either way. */
  fog_of_war: boolean;
  zones: Zone[];
  edges: Edge[];
}

export const getMap = () => api.get<DungeonMap>("/map");
