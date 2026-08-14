# CVM Console v2 (`frontend-v2/`)

The v2 management console: TanStack Router + TanStack Query + Tailwind, served
by `caspar serve` at **`/v2/app`**.

It runs side by side with the v1 console (`frontend/`, at `/app`), which is what
the validated thesis artefact ships and what existing links and documents point
at. Moving `/app` is a product decision, not a build detail — until it is taken,
both are mounted.

The design brief this console was generated from is preserved verbatim in
[`../PROMPT_LOVABLE.md`](../PROMPT_LOVABLE.md), including the non-negotiable
semantics (higher score = worse; `not_assessed` is a third state, never zero or
green). Read it before changing anything that renders a score or a dimension.

## Development

```sh
caspar serve                 # backend on :2027 — start this first
npm install
npm run dev                  # console on :5173
```

The dev server proxies `/api` to `http://127.0.0.1:2027`. There is no CORS
middleware on the backend by design, so the proxy is what keeps the browser
same-origin in development exactly as it is in production. Pointing it at
uvicorn's default `:8000` fails as connection-refused on every API call while
the page itself loads fine — which reads as a broken backend rather than a
misconfigured proxy.

| Script | What it does |
|---|---|
| `npm run dev` | dev server with the `/api` proxy |
| `npm run build` | production bundle into `dist/` |
| `npm test` | Vitest (run once) |
| `npm run test:watch` | Vitest in watch mode |
| `npm run lint` | ESLint |

## The committed `dist/`

**`dist/` is versioned in the repository**, like v1's. Native installs
(`install-native.sh`) have no Node toolchain, so a `git clone` has to arrive
with both consoles already built. `caspar serve` mounts the directory directly
(the `pip install -e` is editable), and soft-fails if it is absent —
`install-native.sh` and the `serve` startup banner both report the absence
rather than advertising a URL that answers 404.

The price is that **editing `src/` obliges a rebuild and a commit**:

```sh
npm run build
git add dist
```

Without that, the served console stays on the previous build while the source
says otherwise — a divergence nothing else catches.

### `base` must stay `/v2/app/`

`vite.config.ts` pins `base` to `process.env.CVM_BASE ?? "/v2/app/"`. A bundle
built for one prefix requests its assets from that prefix wherever it is
actually mounted, so a `dist/` built with the default base produces a blank
page and a 404 on every asset — **the one build mistake that survives a green
`npm run build`**. Do not override `CVM_BASE` for a committed build; it exists
for a future promotion of v2 to `/app`, which would set it once rather than
editing the config, the router and the mount in three separate commits.

`tests/test_serve_cmds.py` asserts both facts against the committed artefact:
that `dist/index.html` exists, and that it references `/v2/app/assets/`.

## Docker

`docker/caspar/Dockerfile` builds this console in its own `console-v2` Node
stage and copies `dist/` into the runtime image — separate from v1's stage, so
the two independent lockfiles do not invalidate each other's npm cache. The
freshly built bundle is copied *after* `COPY . .`, which is what keeps the image
reproducible from source rather than shipping whatever the developer had on
disk; `.dockerignore` excludes `frontend-v2/dist` for the same reason.

`Dockerfile.slim` is untouched and deliberately excludes the API, the dashboard
and both consoles.

## Stack notes

- **Vite 8 / Vitest 4.** Vitest must stay on 4.x: Vitest 3 declares vite
  `^5/^6/^7` and installs its own nested copy, giving one config two Vite type
  identities — which fails to typecheck under `exactOptionalPropertyTypes` with
  an unreadable rollup-vs-rolldown mismatch.
- **`exactOptionalPropertyTypes: true`** in `tsconfig.json`. An optional
  property must be omitted, not set to `undefined`.
- **TanStack Router** with `autoCodeSplitting`, reading the base prefix back
  through `import.meta.env.BASE_URL` so it is declared once in `vite.config.ts`.
- **API key**: never held by this console. `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
  are read from the server process environment only — there is no text input,
  no request-body field, and no CLI flag, because either would end up stored in
  the job record or in shell history. The build page reports whether the
  variable is *present*, never its value.
