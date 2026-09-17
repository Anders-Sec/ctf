/**
 * The theme roster (spec 048).
 *
 * Ids and labels only — every colour value lives in `themes.css`, which is the
 * single source of truth. This file exists so the picker has something to
 * render and so the id list has a typed home.
 *
 * `backend/app/theme.py` holds the same ids for validating a stored preference.
 * `themes.test.ts` asserts the two agree; a theme that exists on one side and
 * not the other is the failure mode that split makes possible, so it is tested
 * rather than trusted.
 */

export const THEME_IDS = [
  "parchment",
  "dark-dungeon",
  "torchlight",
  "high-contrast",
] as const;

export type ThemeId = (typeof THEME_IDS)[number];

/** The theme applied when a user has expressed no preference and the event sets none. */
export const FALLBACK_THEME: ThemeId = "parchment";

export interface Theme {
  id: ThemeId;
  label: string;
  /** One line, shown under the label in the picker. */
  description: string;
  /** Drives `color-scheme`, so native controls and scrollbars match. */
  mode: "light" | "dark";
}

const PARCHMENT: Theme = {
  id: "parchment",
  label: "Parchment",
  description: "Warm and lit. The dungeon as a book you are reading.",
  mode: "light",
};

export const THEMES: Theme[] = [
  PARCHMENT,
  {
    id: "dark-dungeon",
    label: "Dark Dungeon",
    description: "Lights out, torch still burning.",
    mode: "dark",
  },
  {
    id: "torchlight",
    label: "Torchlight",
    description: "Dark, with the contrast turned up for a bright room.",
    mode: "dark",
  },
  {
    id: "high-contrast",
    label: "High Contrast",
    description: "Maximum legibility. Heavy borders, no translucency.",
    mode: "light",
  },
];

export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === "string" && (THEME_IDS as readonly string[]).includes(value);
}

export function themeById(id: string): Theme {
  return THEMES.find((theme) => theme.id === id) ?? PARCHMENT;
}
