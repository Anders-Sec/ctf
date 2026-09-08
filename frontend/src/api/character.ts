import { api } from "./client";

/** A D&D ability score. Progress toward the next point is deliberately hidden —
 *  abilities tick up quietly (spec 018). */
export interface AbilityScore {
  ability: string;
  score: number;
}

/** Name and level only. There is no XP field by design, and `name` is a
 *  placeholder until `discovered` (the real one never leaves the server). */
export interface SkillRow {
  skill_id: string;
  name: string;
  kind: "useful" | "funny";
  level: number;
  discovered: boolean;
}

export interface ClassInfo {
  id: string;
  name: string;
  description: string | null;
}

export interface CharacterSheet {
  user_id: string;
  display_name: string;
  has_avatar: boolean;
  total_xp: number;
  level: number;
  xp_into_level: number;
  xp_to_next: number;
  rank: number | null;
  abilities: AbilityScore[];
  skills: SkillRow[];
  character_class: ClassInfo | null;
  class_unlocked: boolean;
  class_unlock_level: number;
}

export interface PublicCharacter {
  user_id: string;
  display_name: string;
  has_avatar: boolean;
  level: number;
  abilities: AbilityScore[];
  skills: SkillRow[];
  character_class: ClassInfo | null;
}

export const getClasses = () => api.get<ClassInfo[]>("/character/classes");

export const getMyCharacter = () => api.get<CharacterSheet>("/character/me");

export const getCharacter = (userId: string) =>
  api.get<PublicCharacter>(`/character/${userId}`);

/** Set or clear the caller's own class; returns the refreshed sheet. */
export const setMyClass = (classId: string | null) =>
  api.put<CharacterSheet>("/character/class", { class_id: classId });
