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

/** Place a zone, or pass nulls to return it to the derived layout. */
export const setZonePosition = (
  categoryId: string,
  x: number | null,
  y: number | null,
) => api.patch<{ x: number | null; y: number | null }>(
  `/admin/categories/${categoryId}/position`,
  { x, y },
);

/** Clear every authored position — the way out of a layout gone wrong. */
export const resetMapLayout = () =>
  api.post<{ message: string }>("/admin/map/reset-layout");

/** A gate as an admin edits it — the stored row, resolved to names (spec 022). */
export interface Gate {
  id: string;
  requirement_type: RequirementKind;
  description: string;
  required_category_id: string | null;
  required_category_name: string | null;
  required_skill_id: string | null;
  required_skill_name: string | null;
  threshold: number | null;
  /** Advisory: a percentage gate on an empty zone can never be met. */
  source_has_no_challenges: boolean;
}

export type RequirementKind =
  | "challenge_solved"
  | "min_xp"
  | "skill_level"
  | "solves_in_category"
  | "percent_in_category"
  | "player_level";

export interface GraphZone {
  id: string;
  name: string;
  slug: string;
  /** False means no path from a zone that is open at the start. */
  reachable: boolean;
  published_challenges: number;
  gates: Gate[];
}

export const getMapGraph = () =>
  api.get<{ zones: GraphZone[] }>("/admin/map/graph");

export const addCategoryGate = (
  categoryId: string,
  input: {
    requirement_type: RequirementKind;
    required_category_id?: string | null;
    required_skill_id?: string | null;
    threshold?: number | null;
  },
) => api.post<Gate>(`/admin/categories/${categoryId}/requirements`, input);

export const removeGate = (requirementId: string) =>
  api.delete<{ message: string }>(`/admin/requirements/${requirementId}`);
