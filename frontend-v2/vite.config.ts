import { resolve } from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
// From vitest/config, not vite: vite's own defineConfig does not know the
// `test` key, and a /// <reference types="vitest" /> no longer widens it.
//
// Vitest must stay on 4.x. Vitest 3 declares vite ^5/^6/^7 and so installs its
// own nested copy alongside this project's vite 8 — two Vite type identities in
// one config, which fails to typecheck under exactOptionalPropertyTypes with an
// unreadable rollup-vs-rolldown mismatch. 4.x peers on vite 8 and uses this one.
import { defineConfig } from "vitest/config";

/**
 * Static SPA build.
 *
 * This replaced a TanStack Start + nitro configuration that emitted a
 * Cloudflare Worker into `.output/`. `caspar serve` mounts a directory of
 * static files at /app and cannot run a worker, so that build was unusable in
 * both supported installations — and running Node alongside the API would have
 * broken the zero-dependency install the project deliberately keeps.
 *
 * `base` must stay in step with the mount prefix in
 * cli/commands/serve_cmds.py: assets are requested at <base>/assets/*, and a
 * mismatch shows up as a blank page rather than an error. The router reads this
 * same value back through `import.meta.env.BASE_URL`, so the prefix is declared
 * once here and never hand-copied.
 *
 * v2 is mounted at /v2/app while v1 keeps /app. `CVM_BASE` overrides it, which
 * is what a future promotion of v2 to /app would set rather than editing this
 * file and the router and the mount in three separate commits.
 */
export default defineConfig({
  base: process.env["CVM_BASE"] ?? "/v2/app/",
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    // import.meta.dirname, not __dirname: Vite's native config loader (soon
    // the default) does not provide the CJS global and warns on every run.
    alias: { "@": resolve(import.meta.dirname, "./src") },
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
    //
    // 2027 is `caspar serve`'s default port (cli/commands/serve_cmds.py), not
    // uvicorn's 8000. Pointing at 8000 fails as a connection refused on every
    // API call while the page itself loads fine, which reads as a broken
    // backend rather than a misconfigured proxy.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:2027",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    // dist/ holds the built bundle; without this a stale build's JS gets
    // collected as if it were source.
    exclude: ["node_modules/**", "dist/**"],
  },
});
