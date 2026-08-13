import { resolve } from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import { defineConfig } from "vite";

/**
 * Static SPA build.
 *
 * This replaced a TanStack Start + nitro configuration that emitted a
 * Cloudflare Worker into `.output/`. `caspar serve` mounts a directory of
 * static files at /app and cannot run a worker, so that build was unusable in
 * both supported installations — and running Node alongside the API would have
 * broken the zero-dependency install the project deliberately keeps.
 *
 * `base` must stay in step with the router's `basepath` and with the mount
 * prefix in cli/commands/serve_cmds.py: assets are requested at /app/assets/*,
 * and a mismatch shows up as a blank page rather than an error.
 */
export default defineConfig({
  base: "/app/",
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: { "@": resolve(__dirname, "./src") },
  },
  build: {
    // `caspar serve` mounts `dist/`; the SPA fallback there serves index.html
    // for client-side routes.
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    // The API runs in a separate process during development. No CORS
    // middleware exists on the backend by design, so the dev server proxies
    // instead — same-origin in the browser, exactly as in production.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
