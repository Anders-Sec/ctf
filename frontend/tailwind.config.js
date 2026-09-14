/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Colours are referenced through CSS custom properties so the Phase 3 art
      // pass can retheme the whole app by swapping token values in index.css,
      // without touching a single component.
      colors: {
        parchment: "rgb(var(--color-parchment) / <alpha-value>)",
        ink: "rgb(var(--color-ink) / <alpha-value>)",
        muted: "rgb(var(--color-muted) / <alpha-value>)",
        torch: "rgb(var(--color-torch) / <alpha-value>)",
        stone: "rgb(var(--color-stone) / <alpha-value>)",
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
    },
  },
  plugins: [],
};
