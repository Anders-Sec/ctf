import { api } from "./client";

/** Where an accessory sits. One per slot, so two hats cannot share a head. */
export type AccessorySlot = "head" | "eyes" | "shoulders" | "frame";

export type AvatarSource = "sigil" | "entra" | "generated";

export type UnlockKind = "always" | "class" | "achievement" | "loot_rarity";

export interface Accessory {
  slug: string;
  name: string;
  description: string | null;
  slot: AccessorySlot;
  rarity: string;
  /** Computed per request from your class, achievements and loot (spec 073 §2). */
  unlocked: boolean;
  unlock_kind: UnlockKind;
  unlock_ref: string | null;
  /** Where it sits by default. The editor is correction, not composition. */
  anchor_x: number;
  anchor_y: number;
  anchor_scale: number;
  anchor_rotation: number;
}

export interface AvatarLayer {
  accessory: string;
  x: number;
  y: number;
  scale: number;
  rotation: number;
}

export interface MyAvatar {
  source: AvatarSource;
  layers: AvatarLayer[];
  /** Plain words for the crest, so it can be described rather than just shown. */
  description: string;
  has_photo: boolean;
}

export const listAccessories = () => api.get<Accessory[]>("/avatar/accessories");

export const getMyAvatar = () => api.get<MyAvatar>("/avatar/me");

export const saveMyAvatar = (input: { source: AvatarSource; layers: AvatarLayer[] }) =>
  api.put<MyAvatar>("/avatar/me", input);

export const resetMyAvatar = () => api.post<MyAvatar>("/avatar/me/reset");

/** Human words for what earns a locked accessory. */
export function unlockReason(accessory: Accessory): string {
  switch (accessory.unlock_kind) {
    case "class":
      return `Play as ${accessory.unlock_ref}`;
    case "achievement":
      return "Earn a particular achievement";
    case "loot_rarity":
      return `Open ${accessory.unlock_ref} loot`;
    default:
      return "Yours already";
  }
}
