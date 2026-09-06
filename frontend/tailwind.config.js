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
      },
    },
  },
  plugins: [],
};
