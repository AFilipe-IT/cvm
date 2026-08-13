"""
serve_dev.py
------------
Development server that mounts BOTH consoles at once.

`caspar serve` mounts a single console at /app (frontend/dist, the v1 build).
While v2 is being brought to parity, both need to be reachable in one process
so they can be compared against the same database and the same API — two
servers on two ports would answer from two different sets of scan rows the
moment either one writes.

    /app      → frontend-v2/dist   (the target console)
    /app-v1   → frontend/dist      (kept, per the decision to retain v1)

NOT a replacement for `caspar serve`, and deliberately not wired into the CLI:
this exists for local comparison only. The shipped entrypoint stays the one in
cli/commands/serve_cmds.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from config_assessment.api.app import create_app

ROOT = Path(__file__).resolve().parent


class SpaStaticFiles(StaticFiles):
    """StaticFiles with an index.html fallback for client-side routes.

    Client-router paths like /app/knowledge have no matching file on disk.
    Starlette's own html=True only serves index.html for directory-shaped
    requests, so a hard refresh on any page but the root would 404 without
    this. Asset 404s are left alone — masking a missing chunk as index.html
    turns a build problem into a blank page with no error.
    """

    async def get_response(self, path: str, scope: Scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith("assets/"):
                return await super().get_response("index.html", scope)
            raise


def main() -> int:
    db_path = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "ccss.db")
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8100

    if not Path(db_path).exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 2

    app = create_app(db_path=db_path)

    # BOTH bundles were built with base=/app/, so their asset URLs collide and
    # only one can own that prefix. v2 is the target console, so it keeps /app.
    #
    # v1 is served at /app-v1 by rewriting the /app/ prefix in its index.html
    # on the way out, and mounting its assets under /app-v1/assets. Rebuilding
    # v1 with a different base would have been cleaner, but v1 ships a
    # committed dist/ and no node_modules by design — rebuilding it is exactly
    # the thing that setup exists to avoid.
    v1_dist = ROOT / "frontend" / "dist"
    if v1_dist.is_dir():
        from fastapi import Response

        @app.get("/app-v1", include_in_schema=False)
        @app.get("/app-v1/{path:path}", include_in_schema=False)
        def _v1_console(path: str = "") -> Response:
            # Client-side routes have no file on disk; they all get index.html
            # and let the router sort it out. Assets are handled by the mount
            # below, so anything reaching here is a page request.
            html = (v1_dist / "index.html").read_text(encoding="utf-8")
            return Response(html.replace('"/app/', '"/app-v1/'), media_type="text/html")

        app.mount(
            "/app-v1/assets",
            StaticFiles(directory=str(v1_dist / "assets")),
            name="cvm-console-v1-assets",
        )
        print(f"  cvm-console-v1     http://127.0.0.1:{port}/app-v1")
    else:
        # Said out loud rather than silently skipped: a missing bundle and a
        # broken mount look identical from the browser otherwise.
        print(f"  cvm-console-v1     UNAVAILABLE — no bundle at {v1_dist}")

    # Mounted last: a mount at /app would otherwise shadow the /app-v1 routes
    # above, since Starlette matches mounts by prefix in registration order.
    v2_dist = ROOT / "frontend-v2" / "dist"
    if v2_dist.is_dir():
        app.mount("/app", SpaStaticFiles(directory=str(v2_dist), html=True), name="cvm-console-v2")
        print(f"  cvm-console-v2     http://127.0.0.1:{port}/app/")
    else:
        print(f"  cvm-console-v2     UNAVAILABLE — no bundle at {v2_dist}")

    print(f"  api                http://127.0.0.1:{port}/docs")
    print(f"  db                 {db_path}")

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
