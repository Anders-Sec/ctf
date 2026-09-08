import { api } from "./client";

export interface SkillSlice {
  skill_id: string;
  name: string;
  xp: number;
  level: number;
  xp_into_level: number;
  xp_to_next: number;
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
}

export const getMyCharacter = () => api.get<CharacterSheet>("/character/me");

export const getCharacter = (userId: string) =>
  api.get<PublicCharacter>(`/character/${userId}`);
