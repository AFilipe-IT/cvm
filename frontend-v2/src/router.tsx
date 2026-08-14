import { QueryClient } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";

/**
 * The console is served under a mount prefix (see `_mount_frontend` in
 * cli/commands/serve_cmds.py), so the router is told its basepath rather than
 * every <Link> carrying the prefix. Vite's `base` handles the asset URLs; this
 * handles the route URLs, and both must agree or a hard refresh 404s.
 *
 * Both are read from the SAME build-time value: v1 is mounted at /app and v2 at
 * /v2/app, and keeping the prefix in two hand-edited literals is how a bundle
 * ends up requesting its assets from one prefix while routing against another —
 * a blank page with no error to explain it.
 *
 * `import.meta.env.BASE_URL` is what Vite substitutes for its own `base`, with
 * the trailing slash the router does not want.
 */
const BASEPATH = import.meta.env.BASE_URL.replace(/\/$/, "") || "/";
export const getRouter = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        // Posture data changes when a scan runs, not on focus. Refetching on
        // every window focus would put avoidable load on an endpoint that
        // re-reads the latest scan of every configuration.
        refetchOnWindowFocus: false,
        staleTime: 30_000,
        retry: 1,
      },
    },
  });

  return createRouter({
    routeTree,
    context: { queryClient },
    basepath: BASEPATH,
    scrollRestoration: true,
    defaultPreloadStaleTime: 0,
  });
};

// Registers the router's type so `useNavigate`, `Link` and `useSearch` are
// typed against the real route tree. The SSR build declared this against
// `@tanstack/react-start`; with Start removed the declaration has to live
// here, and without it every `search` callback silently degrades to `any`.
declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof getRouter>;
  }
}
