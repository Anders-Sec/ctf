import { api } from "./client";
import type { BossStar } from "./scoreboard";

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

/** Colour only — never a gate and never a score (spec 024). */
export type Rarity = "common" | "uncommon" | "rare" | "legendary" | "mythic";

export interface ClassInfo {
  id: string;
  name: string;
  description: string | null;
  rarity: Rarity;
}

/** Just enough to name a party and link to it (spec 060 §6). */
export interface PartyBrief {
  id: string;
  name: string;
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
  /** The System AI's read on which class fits. Never a locked one. */
  suggested_class: ClassInfo | null;
  /** The nudge, already written in the System AI's voice (specs 013, 016). */
  suggested_class_line: string | null;
  class_unlock_level: number;
  /** The party they are in, so the sheet describes the character on its own. */
  party: PartyBrief | null;
  /** The worn loot title — the name plate everybody else sees on the board. */
  equipped_title: string | null;
}

/** Counts only. A per-zone XP total would be XP wearing a different hat. */
export interface ZoneSolves {
  zone_name: string;
  solves: number;
}

/** Somebody else's sheet (spec 061). No XP in any form, and no loot. */
export interface PublicCharacter {
  user_id: string;
  display_name: string;
  has_avatar: boolean;
  level: number;
  abilities: AbilityScore[];
  /** Every row is discovered — the server sends nothing else. */
  skills: SkillRow[];
  character_class: ClassInfo | null;
  /** Null for anybody the board does not hold, staff accounts included. */
  rank: number | null;
  party: PartyBrief | null;
  equipped_title: string | null;
  /** The list carries only discovered rows, so `N of M` needs M separately. */
  skills_total: number;
  stars: BossStar[];
  solve_count: number;
  zones: ZoneSolves[];
}

/**
 * One row of somebody else's trophy case (spec 061 §4).
 *
 * `name` and `rarity` are both null when the row is a secret the viewer has not
 * earned. Redacted server-side — there is nothing here to un-blur.
 */
export interface PublicAchievement {
  id: string;
  name: string | null;
  rarity: number | null;
}

export interface PublicAchievements {
  earned: number;
  /** Earned but not nameable to this viewer. Hidden from the display at zero. */
  secret_count: number;
  items: PublicAchievement[];
  /** The five rarest the viewer can see named. */
  rarest: PublicAchievement[];
}

export const getClasses = () => api.get<ClassInfo[]>("/character/classes");

export const getMyCharacter = () => api.get<CharacterSheet>("/character/me");

export const getCharacter = (userId: string) =>
  api.get<PublicCharacter>(`/character/${userId}`);

export const getPublicAchievements = (userId: string) =>
  api.get<PublicAchievements>(`/character/${userId}/achievements`);

/** Set or clear the caller's own class; returns the refreshed sheet. */
export const setMyClass = (classId: string | null) =>
  api.put<CharacterSheet>("/character/class", { class_id: classId });
