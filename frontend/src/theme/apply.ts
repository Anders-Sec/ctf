/**
 * Applying a theme to the document (spec 048).
 *
 * Two writers, deliberately in this order:
 *
 *  1. The inline snippet in `index.html` stamps `data-theme` from localStorage
 *     before the bundle parses, so the first paint is already correct. Without
 *     it every dark-theme user sees a parchment flash on every navigation.
 *  2. React reconciles that against the server-held preference once the session
 *     loads. The server is the source of truth — the localStorage copy exists
 *     only to win the race against the network.
 */

import {
  FALLBACK_THEME,
  HIGH_CONTRAST_THEME,
  isThemeId,
  themeById,
  type ThemeId,
} from "./themes";

export const THEME_STORAGE_KEY = "ctf.theme";

/**
 * Stamp the document. Also sets `color-scheme` so native controls, scrollbars
 * and form widgets follow the theme — without it a dark page renders white
 * dropdowns and a white scrollbar gutter.
 */
export function applyTheme(id: ThemeId): void {
  const root = document.documentElement;
  root.setAttribute("data-theme", id);
  root.style.colorScheme = themeById(id).mode;
}

/**
 * The cached preference, if it is still a theme we recognise.
 *
 * Every access is guarded: `localStorage` throws outright in some privacy
 * modes, and a theme that cannot be read is not a reason to fail to render a
 * page.
 */
export function readStoredTheme(): ThemeId | null {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeId(stored) ? stored : null;
  } catch {
    return null;
  }
}

export function storeTheme(id: ThemeId): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, id);
  } catch {
    // A preference we cannot cache still works; it just flashes on next load.
  }
}

/**
 * Resolve what a session should actually be showing.
 *
 * High contrast is a second axis, not a third theme: while it is on it wins
 * outright, and the underlying choice is left untouched so turning it off
 * returns the player to the side of the toggle they were on.
 *
 * An unrecognised name — a preset removed after somebody selected it — falls
 * back rather than throwing. A stored preference must never be able to break a
 * login.
 */
export function resolveTheme(
  userTheme: string | null | undefined,
  eventDefault: string | null | undefined,
  highContrast = false,
): ThemeId {
  if (highContrast) return HIGH_CONTRAST_THEME;
  if (isThemeId(userTheme)) return userTheme;
  if (isThemeId(eventDefault)) return eventDefault;
  return FALLBACK_THEME;
}
