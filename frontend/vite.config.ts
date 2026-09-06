import react from "@vitejs/plugin-react";
// defineConfig comes from vitest/config, not vite, so the `test` block typechecks.
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    // Not Vite's default 5173: Windows reserves chunks of the 5000s for dynamic
    // allocation, and 5173 commonly lands inside one. See the README.
    port: 4173,
    strictPort: true,
    proxy: {
      // Same-origin in development, so cookies and CORS behave the way they will
      // behind the ingress. CORS_ALLOWED_ORIGINS covers the split-origin deploy.
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
