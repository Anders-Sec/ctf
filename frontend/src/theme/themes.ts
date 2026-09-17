/**
 * The theme roster (spec 048, amended §10).
 *
 * Ids and metadata only — every colour value lives in `themes.css`, which is the
 * single source of truth. This file exists so the controls have something to
 * render and so the id list has a typed home.
 *
 * `backend/app/theme.py` holds the same ids for validating a stored preference.
 * `themes.test.ts` asserts the two agree; a theme present on one side and not
 * the other is the failure mode that split makes possible, so it is tested
 * rather than trusted.
 */

export const THEME_IDS = [
  "parchment",
  "dark-dungeon",
  "high-contrast",
  "purple-squirrel",
  "dnd",
  "mr-anderson",
] as const;

export type ThemeId = (typeof THEME_IDS)[number];

/** The theme applied when a user has expressed no preference and the event sets none. */
export const FALLBACK_THEME: ThemeId = "parchment";

/** The two sides of the everyday toggle. */
export const LIGHT_THEME: ThemeId = "parchment";
export const DARK_THEME: ThemeId = "dark-dungeon";

/**
 * The accessibility switch, not an entry in any list of looks.
 *
 * It overrides whatever theme is selected while it is on, which is why it is
 * stored as its own flag rather than as a theme choice — turning it off has to
 * return the player to the side of the toggle they were on.
 */
export const HIGH_CONTRAST_THEME: ThemeId = "high-contrast";

export interface Theme {
  id: ThemeId;
  label: string;
  /** One line, shown under the label wherever the theme is offered. */
  description: string;
  /** Drives `color-scheme`, so native controls and scrollbars match. */
  mode: "light" | "dark";
  /**
   * Not offered by the light/dark toggle. How a player comes to hold one of
   * these is deliberately undecided (spec 048 §11.4); the admin can select any
   * of them today.
   */
  secret?: true;
  /**
   * Exempt from the contrast assertions in `themes.test.ts`.
   *
   * Exactly one theme carries this, and it is a gag. Declaring the exemption
   * here — rather than weakening the test — keeps it a recorded decision
   * instead of a theme that quietly fails.
   */
  exemptFromContrast?: true;
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
    id: "high-contrast",
    label: "High Contrast",
    description: "Maximum legibility. Heavy borders, no translucency.",
    mode: "light",
  },
  {
    id: "purple-squirrel",
    label: "Purple Squirrel",
    description: "You know why.",
    mode: "dark",
    secret: true,
    exemptFromContrast: true,
  },
  {
    id: "dnd",
    label: "DND",
    description: "Tavern candlelight, leather and old gold.",
    mode: "dark",
    secret: true,
  },
  {
    id: "mr-anderson",
    label: "The Mr. Anderson",
    description: "Green on black. Follow the white rabbit.",
    mode: "dark",
    secret: true,
  },
];

/** What the everyday toggle offers: light, dark, and nothing else. */
export const TOGGLE_THEMES: Theme[] = THEMES.filter(
  (theme) => theme.id === LIGHT_THEME || theme.id === DARK_THEME,
);

/** Every theme an admin may assign, which is all of them. */
export const SELECTABLE_THEMES: Theme[] = THEMES;

export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === "string" && (THEME_IDS as readonly string[]).includes(value);
}

export function themeById(id: string): Theme {
  return THEMES.find((theme) => theme.id === id) ?? PARCHMENT;
}
