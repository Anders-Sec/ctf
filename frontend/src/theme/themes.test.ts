import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { resolveTheme, THEME_STORAGE_KEY } from "./apply";
import { FALLBACK_THEME, isThemeId, THEME_IDS, THEMES } from "./themes";

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

  for (const id of THEME_IDS) {
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
    expect(resolveTheme("torchlight", "dark-dungeon")).toBe("torchlight");
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
    expect(resolveTheme("midnight-gala", "torchlight")).toBe("torchlight");
    expect(isThemeId("midnight-gala")).toBe(false);
  });
});

describe("the anti-flash stamp in index.html", () => {
  // The snippet cannot import anything — it runs before the bundle parses — so
  // it carries its own copy of the roster. That copy is the drift risk, and
  // this is what keeps it honest.
  const HTML = readFileSync(resolve(process.cwd(), "index.html"), "utf8");

  it("knows exactly the themes the roster knows", () => {
    const listed = /var known = \[([^\]]*)\]/.exec(HTML)?.[1];
    expect(listed, "no theme list found in the inline snippet").toBeTruthy();
    const names = [...(listed ?? "").matchAll(/"([a-z-]+)"/g)].map((m) => m[1]);
    expect(names.sort()).toEqual([...THEME_IDS].sort());
  });

  it("agrees with the roster about which themes are dark", () => {
    const dark = THEMES.filter((theme) => theme.mode === "dark").map((theme) => theme.id);
    for (const id of dark) {
      expect(HTML, `${id} is dark but the snippet does not say so`).toContain(`"${id}"`);
    }
    // The snippet's dark test is a literal comparison; assert its shape so a
    // new dark preset cannot be silently left out of it.
    const test = /stored === "([a-z-]+)" \|\| stored === "([a-z-]+)"/.exec(HTML);
    expect(test?.slice(1, 3).sort()).toEqual(dark.sort());
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
