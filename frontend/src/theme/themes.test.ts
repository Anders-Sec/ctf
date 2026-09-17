import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { resolveTheme, THEME_STORAGE_KEY } from "./apply";
import {
  DARK_THEME,
  FALLBACK_THEME,
  HIGH_CONTRAST_THEME,
  isThemeId,
  LIGHT_THEME,
  THEME_IDS,
  THEMES,
  TOGGLE_THEMES,
  themeById,
} from "./themes";

/**
 * These tests parse `themes.css` rather than importing values from TypeScript,
 * because the CSS is what ships. A generator in between would mean testing the
 * inputs to a build step instead of the thing the browser paints.
 *
 * The contrast block is the test that justifies curated presets over a colour
 * picker (spec 048 §4) — so it is not optional, and a new preset cannot land
 * without passing it.
 */

// Resolved from the vitest root (frontend/) rather than import.meta.url: under
// the jsdom environment that is not a file: URL.
const CSS = readFileSync(resolve(process.cwd(), "src/theme/themes.css"), "utf8");

/** Every role a theme must define. Missing one is a half-painted page. */
const ROLES = [
  "surface",
  "surface-raised",
  "surface-sunken",
  "surface-overlay",
  "border",
  "border-strong",
  "content",
  "content-muted",
  "content-faint",
  "accent",
  "accent-strong",
  "accent-content",
  "danger",
  "warning",
  "success",
  "info",
  "focus-ring",
] as const;

type Rgb = [number, number, number];

/**
 * Pull one theme's declarations out of the stylesheet.
 *
 * The default theme is the bare `:root` block that also opens the file; a named
 * theme is its `:root[data-theme="…"]` block.
 */
function block(themeId: string): string {
  const selector =
    themeId === FALLBACK_THEME
      ? "\\:root\\s*\\{"
      : `\\:root\\[data-theme="${themeId}"\\]\\s*\\{`;
  const body = new RegExp(`${selector}([^}]*)\\}`).exec(CSS)?.[1];
  if (!body) throw new Error(`no CSS block for theme "${themeId}"`);
  return body;
}

function tokens(themeId: string): Map<string, Rgb> {
  const found = new Map<string, Rgb>();
  const declarations = block(themeId).matchAll(
    /--([a-z-]+):\s*(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})\s*;/g,
  );
  for (const [, name, r, g, b] of declarations) {
    if (!name) continue;
    found.set(name, [Number(r), Number(g), Number(b)]);
  }
  return found;
}

/** WCAG relative luminance. */
function luminance([r, g, b]: Rgb): number {
  const channel = (value: number) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(a: Rgb, b: Rgb): number {
  const light = Math.max(luminance(a), luminance(b));
  const dark = Math.min(luminance(a), luminance(b));
  return (light + 0.05) / (dark + 0.05);
}

describe("theme roster", () => {
  it("defines every role in every preset", () => {
    for (const id of THEME_IDS) {
      const defined = tokens(id);
      const missing = ROLES.filter((role) => !defined.has(role));
      expect(missing, `theme "${id}" is missing roles`).toEqual([]);
    }
  });

  it("has a roster entry for every preset, and no orphans", () => {
    expect(THEMES.map((theme) => theme.id)).toEqual([...THEME_IDS]);
  });

  it("offers exactly light and dark on the everyday toggle", () => {
    // Spec 048 §10: four presets turned out to be two. A toggle is the right
    // shape for a two-way choice, and everything else moved to settings or
    // behind an unlock.
    expect(TOGGLE_THEMES.map((theme) => theme.id)).toEqual([LIGHT_THEME, DARK_THEME]);
    expect(themeById(LIGHT_THEME).mode).toBe("light");
    expect(themeById(DARK_THEME).mode).toBe("dark");
  });

  it("keeps high contrast and the secret themes off the toggle", () => {
    const offered = new Set(TOGGLE_THEMES.map((theme) => theme.id));
    expect(offered.has(HIGH_CONTRAST_THEME)).toBe(false);
    for (const theme of THEMES.filter((t) => t.secret)) {
      expect(offered.has(theme.id)).toBe(false);
    }
  });

  it("carries the three secret themes", () => {
    expect(THEMES.filter((theme) => theme.secret).map((theme) => theme.id)).toEqual([
      "purple-squirrel",
      "dnd",
      "mr-anderson",
    ]);
  });

  it("no longer carries torchlight", () => {
    // It was meant to be the high-contrast dark and read as Dark Dungeon two
    // values apart.
    expect(isThemeId("torchlight")).toBe(false);
    expect(CSS).not.toContain("torchlight");
  });

  it("agrees with the backend roster", () => {
    // A theme present on one side and not the other renders as nothing, or is
    // refused on save. Two lists are the cost of not sharing a build context
    // between the images; this is what keeps them honest.
    const python = readFileSync(
      resolve(process.cwd(), "../backend/app/theme.py"),
      "utf8",
    );
    const listed = [...python.matchAll(/^\s{4}"([a-z-]+)",$/gm)].map((m) => m[1] ?? "");
    expect(listed).toEqual([...THEME_IDS]);
    expect(python).toContain(`FALLBACK_THEME: Final[str] = "${FALLBACK_THEME}"`);
  });
});

describe("contrast", () => {
  // AA: 4.5:1 for body text, 3:1 for large text and UI boundaries.
  const BODY = 4.5;
  const UI = 3;

  // Exactly one theme opts out, and it declares the exemption in the roster
  // rather than the test naming it — so adding a second exempt theme is a
  // visible edit to the roster, not a quiet edit to a test.
  const asserted = THEMES.filter((theme) => !theme.exemptFromContrast).map((t) => t.id);

  it("exempts only what the roster declares exempt", () => {
    expect(THEMES.filter((theme) => theme.exemptFromContrast).map((t) => t.label)).toEqual([
      "Purple Squirrel",
    ]);
  });

  for (const id of asserted) {
    describe(id, () => {
      const token = (name: string): Rgb => {
        const value = tokens(id).get(name);
        if (!value) throw new Error(`theme "${id}" has no --${name}`);
        return value;
      };

      const readable = (fg: string, bg: string, minimum: number) => {
        const ratio = contrast(token(fg), token(bg));
        expect(
          ratio,
          `${fg} on ${bg} is ${ratio.toFixed(2)}:1, needs ${minimum}:1`,
        ).toBeGreaterThanOrEqual(minimum);
      };

      it("body text is readable on both surfaces", () => {
        readable("content", "surface", BODY);
        readable("content", "surface-raised", BODY);
        readable("content", "surface-overlay", BODY);
      });

      it("muted text is readable on both surfaces", () => {
        readable("content-muted", "surface", BODY);
        readable("content-muted", "surface-raised", BODY);
      });

      it("accent text is readable, and accent fills carry their label", () => {
        readable("accent-strong", "surface", BODY);
        readable("accent-strong", "surface-raised", BODY);
        readable("accent-content", "accent", BODY);
      });

      it("status colours are readable on both surfaces", () => {
        for (const status of ["danger", "warning", "success", "info"]) {
          readable(status, "surface", BODY);
          readable(status, "surface-raised", BODY);
        }
      });

      it("control boundaries and focus rings meet the UI threshold", () => {
        // WCAG 1.4.11 is about boundaries a user must be able to find — an
        // input outline, a focus ring. `border` is excluded deliberately: it is
        // a decorative hairline between rows, and holding it to 3:1 would make
        // every theme draw heavy black rules between table rows.
        readable("border-strong", "surface", UI);
        readable("focus-ring", "surface", UI);
        readable("focus-ring", "surface-raised", UI);
      });

      it("the hairline border is at least perceptible", () => {
        const ratio = contrast(token("border"), token("surface"));
        expect(
          ratio,
          `border on surface is ${ratio.toFixed(2)}:1 — invisible`,
        ).toBeGreaterThan(1.2);
      });

      it("a raised surface is distinguishable from the page", () => {
        // Not a WCAG rule — a card that cannot be told apart from the page is
        // just a card nobody can see. High Contrast is exempt: it separates
        // regions with heavy borders instead, deliberately.
        if (id === "high-contrast") return;
        const ratio = contrast(token("surface-raised"), token("surface"));
        expect(ratio).toBeGreaterThan(1.05);
      });
    });
  }
});

describe("resolving a preference", () => {
  it("prefers the user's choice", () => {
    expect(resolveTheme("mr-anderson", "dark-dungeon")).toBe("mr-anderson");
  });

  it("lets high contrast override whatever is selected", () => {
    expect(resolveTheme("dnd", "parchment", true)).toBe(HIGH_CONTRAST_THEME);
    expect(resolveTheme(null, null, true)).toBe(HIGH_CONTRAST_THEME);
  });

  it("puts back the underlying choice when high contrast goes off", () => {
    // The whole reason it is a separate flag rather than a theme value.
    expect(resolveTheme("dnd", "parchment", false)).toBe("dnd");
  });

  it("falls back to the event default when the user has no choice", () => {
    expect(resolveTheme(null, "dark-dungeon")).toBe("dark-dungeon");
  });

  it("falls back to the default theme when neither is set", () => {
    expect(resolveTheme(null, null)).toBe(FALLBACK_THEME);
  });

  it("ignores a theme that no longer exists rather than breaking", () => {
    // A preset removed after somebody selected it. This must degrade, not throw
    // — it is read on every session load.
    expect(resolveTheme("midnight-gala", null)).toBe(FALLBACK_THEME);
    expect(resolveTheme("midnight-gala", "dark-dungeon")).toBe("dark-dungeon");
    expect(isThemeId("midnight-gala")).toBe(false);
  });
});

describe("the anti-flash stamp in index.html", () => {
  // The snippet cannot import anything — it runs before the bundle parses — so
  // it carries its own copy of the roster. That copy is the drift risk, and
  // this is what keeps it honest.
  const HTML = readFileSync(resolve(process.cwd(), "index.html"), "utf8");

  /** The snippet's own copy of the roster, as a theme → mode map. */
  function snippetModes(): Record<string, string> {
    const body = /var MODES = \{([^}]*)\}/.exec(HTML)?.[1];
    expect(body, "no MODES map found in the inline snippet").toBeTruthy();
    const modes: Record<string, string> = {};
    for (const [, id, mode] of (body ?? "").matchAll(/"([a-z-]+)":\s*"(light|dark)"/g)) {
      modes[id!] = mode!;
    }
    return modes;
  }

  it("knows exactly the themes the roster knows", () => {
    expect(Object.keys(snippetModes()).sort()).toEqual([...THEME_IDS].sort());
  });

  it("agrees with the roster about which themes are dark", () => {
    const modes = snippetModes();
    for (const theme of THEMES) {
      expect(modes[theme.id], `${theme.id} should be ${theme.mode} in the snippet`).toBe(
        theme.mode,
      );
    }
  });

  it("reads the same storage key the app writes", () => {
    expect(HTML).toContain(`"${THEME_STORAGE_KEY}"`);
  });
});

describe("themes do not disturb motion preferences", () => {
  // Spec 023 budgeted the map's animations deliberately and turns every one of
  // them off under reduced-motion. A theme changes colour; it must not be able
  // to reintroduce movement behind that guard.
  const INDEX_CSS = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");

  it("keeps the reduced-motion guards in place", () => {
    const guards = INDEX_CSS.match(/@media \(prefers-reduced-motion: reduce\)/g) ?? [];
    expect(guards.length).toBeGreaterThanOrEqual(2);
    for (const name of ["dungeon-torch", "dungeon-fog", "dungeon-mote"]) {
      expect(INDEX_CSS).toContain(name);
    }
  });

  it("defines no animation or transition in any theme block", () => {
    for (const id of THEME_IDS) {
      expect(block(id)).not.toMatch(/animation|transition|@keyframes/);
    }
  });
});
