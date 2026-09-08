import { api } from "./client";

export interface SkillSlice {
  skill_id: string;
  name: string;
  xp: number;
  level: number;
  xp_into_level: number;
  xp_to_next: number;
}

export interface ClassInfo {
  id: string;
  name: string;
  description: string | null;
}

export interface SuggestedClass {
  class_id: string;
  name: string;
  from_skill: string;
  /** The System AI's voiced line (spec 016) — deterministic persona copy. */
  narration: string;
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
  skills: SkillSlice[];
  character_class: ClassInfo | null;
  suggested_class: SuggestedClass | null;
  class_unlocked: boolean;
  class_unlock_level: number;
}

export interface PublicSkill {
  skill_id: string;
  name: string;
  level: number;
}

export interface PublicCharacter {
  user_id: string;
  display_name: string;
  has_avatar: boolean;
  level: number;
  skills: PublicSkill[];
  character_class: ClassInfo | null;
}

export const getClasses = () => api.get<ClassInfo[]>("/character/classes");

export const getMyCharacter = () => api.get<CharacterSheet>("/character/me");

export const getCharacter = (userId: string) =>
  api.get<PublicCharacter>(`/character/${userId}`);

/** Set or clear the caller's own class; returns the refreshed sheet. */
export const setMyClass = (classId: string | null) =>
  api.put<CharacterSheet>("/character/class", { class_id: classId });
