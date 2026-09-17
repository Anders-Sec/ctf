/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Colours are referenced through CSS custom properties, so a theme is a
      // block of token values in `src/theme/themes.css` and nothing else — no
      // component names a colour, and adding a preset touches no component.
      //
      // The names below are ROLES, not pigments. `surface` is "the page", not
      // "the parchment": naming them after the light theme's pigments is what
      // made a dark theme impossible to express before spec 048.
      colors: {
        surface: {
          DEFAULT: "rgb(var(--surface) / <alpha-value>)",
          raised: "rgb(var(--surface-raised) / <alpha-value>)",
          sunken: "rgb(var(--surface-sunken) / <alpha-value>)",
          overlay: "rgb(var(--surface-overlay) / <alpha-value>)",
        },
        border: {
          DEFAULT: "rgb(var(--border) / <alpha-value>)",
          strong: "rgb(var(--border-strong) / <alpha-value>)",
        },
        content: {
          DEFAULT: "rgb(var(--content) / <alpha-value>)",
          muted: "rgb(var(--content-muted) / <alpha-value>)",
          faint: "rgb(var(--content-faint) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",
          strong: "rgb(var(--accent-strong) / <alpha-value>)",
          content: "rgb(var(--accent-content) / <alpha-value>)",
        },
        danger: "rgb(var(--danger) / <alpha-value>)",
        warning: "rgb(var(--warning) / <alpha-value>)",
        success: "rgb(var(--success) / <alpha-value>)",
        info: "rgb(var(--info) / <alpha-value>)",

        // Text on a saturated fill — a puzzle tile, a generated avatar.
        "on-fill": "rgb(var(--on-fill) / <alpha-value>)",

        // Puzzle boards (spec 044). Theme-invariant: green/amber/grey on a
        // Wordle tile is a convention players arrive already knowing.
        puzzle: {
          exact: "rgb(var(--puzzle-exact) / <alpha-value>)",
          present: "rgb(var(--puzzle-present) / <alpha-value>)",
          absent: "rgb(var(--puzzle-absent) / <alpha-value>)",
          "level-1": "rgb(var(--puzzle-level-1) / <alpha-value>)",
          "level-2": "rgb(var(--puzzle-level-2) / <alpha-value>)",
          "level-3": "rgb(var(--puzzle-level-3) / <alpha-value>)",
          "level-4": "rgb(var(--puzzle-level-4) / <alpha-value>)",
          "level-content": "rgb(var(--puzzle-level-content) / <alpha-value>)",
        },

        // Legacy pigment names, aliased onto the roles in themes.css. Kept so
        // the migration is incremental; removed once nothing references them.
        parchment: "rgb(var(--color-parchment) / <alpha-value>)",
        ink: "rgb(var(--color-ink) / <alpha-value>)",
        muted: "rgb(var(--color-muted) / <alpha-value>)",
        torch: "rgb(var(--color-torch) / <alpha-value>)",
        stone: "rgb(var(--color-stone) / <alpha-value>)",

        // The six-step rarity ladder is deliberately theme-invariant — see the
        // note in themes.css.
        loot: {
          bronze: "rgb(var(--color-loot-bronze) / <alpha-value>)",
          silver: "rgb(var(--color-loot-silver) / <alpha-value>)",
          gold: "rgb(var(--color-loot-gold) / <alpha-value>)",
          platinum: "rgb(var(--color-loot-platinum) / <alpha-value>)",
          legendary: "rgb(var(--color-loot-legendary) / <alpha-value>)",
          celestial: "rgb(var(--color-loot-celestial) / <alpha-value>)",
        },
        boss: {
          neighborhood: "rgb(var(--color-boss-neighborhood) / <alpha-value>)",
          borough: "rgb(var(--color-boss-borough) / <alpha-value>)",
          city: "rgb(var(--color-boss-city) / <alpha-value>)",
          province: "rgb(var(--color-boss-province) / <alpha-value>)",
          country: "rgb(var(--color-boss-country) / <alpha-value>)",
          floor: "rgb(var(--color-boss-floor) / <alpha-value>)",
        },
        rarity: {
          common: "rgb(var(--color-rarity-common) / <alpha-value>)",
          uncommon: "rgb(var(--color-rarity-uncommon) / <alpha-value>)",
          rare: "rgb(var(--color-rarity-rare) / <alpha-value>)",
          legendary: "rgb(var(--color-rarity-legendary) / <alpha-value>)",
          mythic: "rgb(var(--color-rarity-mythic) / <alpha-value>)",
        },
      },
      ringColor: {
        DEFAULT: "rgb(var(--focus-ring) / <alpha-value>)",
        focus: "rgb(var(--focus-ring) / <alpha-value>)",
      },
      outlineColor: {
        focus: "rgb(var(--focus-ring) / <alpha-value>)",
      },
    },
  },
  plugins: [],
};
