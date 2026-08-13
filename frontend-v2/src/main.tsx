/**
 * src/main.tsx
 * ------------
 * Client entry for the CVM console.
 *
 * The console is a STATIC SPA, not a server-rendered app. `caspar serve` mounts
 * a directory of files and nothing more, which is what keeps the two supported
 * installations free of a Node runtime — the SSR build this replaced emitted a
 * Cloudflare Worker, which nothing in the deployment story could execute.
 *
 * Every page here reads live data from /api/v1 at runtime, so there was no
 * server-rendered content to lose: pre-rendering a dashboard whose numbers come
 * from the API would ship a shell that is immediately replaced.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { getRouter } from "./router";
import "./styles.css";

const router = getRouter();
const queryClient = router.options.context.queryClient;

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("index.html is missing #root — the app has nowhere to mount.");
}

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
