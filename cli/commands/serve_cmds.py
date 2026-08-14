"""
cli/commands/serve_cmds.py — `caspar serve`.

Launches the REST API (config_assessment/api/) and the CVM Console
(frontend/dist) in one Uvicorn process, both mounted on the same FastAPI app
so they share one CVM Core and one DB connection pool.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click


@click.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True,
              help="Bind address. Use 0.0.0.0 to expose beyond localhost.")
@click.option("--port", default=2027, show_default=True, type=int)
@click.option("--reload", is_flag=True, default=False,
              help="Auto-reload on source changes (development only).")
@click.pass_context
def serve(ctx: click.Context, host: str, port: int, reload: bool) -> None:
    """Serve the REST API + CVM Console (same CVM Core as `caspar scan`).

    \b
    Swagger UI:       http://127.0.0.1:2027/docs
    CVM Console:      http://127.0.0.1:2027/app      (v2, primary)
    CVM Console (v1): http://127.0.0.1:2027/v1/app
    """
    # As dependências do servidor são um extra opcional: quem só usa a CLI não
    # precisa de instalar fastapi/uvicorn. Sem esta captura, um `pip install -e .`
    # sem o extra (o que o install-native.sh evita, mas quem instala à mão faz)
    # rebentava com um traceback de ModuleNotFoundError, que não diz a ninguém
    # qual é o comando que falta.
    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        click.echo(
            click.style(f"O 'caspar serve' precisa do extra [api] (falta: {exc.name}).\n",
                        fg="yellow") +
            "Instale com: " + click.style('pip install -e ".[api]"', bold=True) + "\n"
            "A CLI (scan, build, plugin, report) funciona sem ele.",
            err=True,
        )
        sys.exit(2)

    db_path: str = ctx.obj["db_path"]
    if not Path(db_path).exists():
        click.echo(
            click.style(f"DB '{db_path}' not found.\n", fg="yellow") +
            "Run: " + click.style("caspar build --benchmark <pdf>", bold=True),
            err=True,
        )
        sys.exit(2)

    click.echo(click.style(f"  DB: {db_path}", dim=True))
    click.echo(click.style(f"  Swagger UI:  http://{host}:{port}/docs", fg="cyan"))
    # Announcing a console unconditionally sent people to a URL that 404s when
    # the bundle isn't there. The mounts are soft-failing by design, so the
    # startup lines are the only place an absence can be reported.
    #
    # v2 is the primary console and answers at /app; v1 stays available at
    # /v1/app. The v2 line carries the warning branch because /app is the URL
    # everyone opens — an absence there is what needs explaining.
    if _console_v2_dist().is_dir():
        click.echo(click.style(f"  CVM Console: http://{host}:{port}/app", fg="cyan"))
    else:
        click.echo(click.style(
            "  CVM Console: unavailable — the frontend bundle is missing.\n"
            "               Reinstall (./install-native.sh) or use the Docker "
            "image, which ships it.", fg="yellow"))
    if _console_dist().is_dir():
        click.echo(click.style(f"  CVM Console (v1): http://{host}:{port}/v1/app",
                               fg="cyan"))
    click.echo()

    if reload:
        # Uvicorn's reloader re-imports the app by string path; db_path must
        # travel via env var since a fresh process re-executes create_app().
        import os
        os.environ["CASPAR_DB"] = db_path
        uvicorn.run("cli.commands.serve_cmds:_reload_app", host=host, port=port, reload=True, factory=True)
    else:
        from config_assessment.api.app import create_app
        app = create_app(db_path=db_path)
        _mount_frontend(app)
        uvicorn.run(app, host=host, port=port)


def _console_dist() -> Path:
    """The v1 console's bundle, served at /v1/app.

    One function so `serve` cannot advertise a console the mount then declines
    to serve — the two used to derive the path independently.

    v1 moved off /app when v2 was promoted to primary. It is kept because it is
    what the validated thesis artefact ships and what the dissertation's figures
    show; /v1/app is a stable home for it rather than a deprecation."""
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _console_v2_dist() -> Path:
    """The v2 console's bundle — the primary console, served at /app.

    Each bundle must be built with `base` equal to the prefix it is mounted at
    (v2 /app/, v1 /v1/app/): a bundle built for one prefix requests its assets
    from that prefix wherever it is actually mounted, which surfaces as a blank
    page rather than an error. Both are pinned in the respective
    vite.config.ts and asserted in tests/test_serve_cmds.py."""
    return Path(__file__).resolve().parents[2] / "frontend-v2" / "dist"


def _mount_frontend(app) -> None:
    """Mount the built React consoles: v2 at /app (primary), v1 at /v1/app.

    Both bundles are committed to the repository and the Docker image builds
    its own, so in every supported installation they are there — neither
    console requires Node at install time. Soft-failing covers the remaining
    case, a source tree whose dist was cleaned, where the REST API is still
    useful on its own; `serve` reports the absence on startup.

    Neither prefix collides with anything already routed: /api/v1/*,
    /dashboard*, /docs, /redoc and /openapi.json are the taken ones, and a
    mount claims only its own subtree."""
    from fastapi.staticfiles import StaticFiles
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from starlette.types import Scope

    class SpaStaticFiles(StaticFiles):
        """StaticFiles with an index.html fallback for client-side routes.

        React Router paths like /app/knowledge-base have no matching file on
        disk — Starlette's own html=True only serves index.html for
        directory-shaped requests, not arbitrary sub-paths, so a hard
        refresh on any page but /app/ would 404 without this."""

        async def get_response(self, path: str, scope: Scope):
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                if exc.status_code == 404 and not path.startswith("assets/"):
                    return await super().get_response("index.html", scope)
                raise

    # Starlette matches mounts in registration order, so the more specific
    # prefix goes first: /v1/app is not a sub-path of /app (a mount matches on
    # whole path segments, and "v1" != "app"), but registering it first keeps
    # correctness independent of how these prefixes change again.
    if _console_dist().is_dir():
        app.mount("/v1/app",
                  SpaStaticFiles(directory=str(_console_dist()), html=True),
                  name="cvm-console-v1")
    if _console_v2_dist().is_dir():
        app.mount("/app",
                  SpaStaticFiles(directory=str(_console_v2_dist()), html=True),
                  name="cvm-console")


def _reload_app():
    """Factory target for `uvicorn --reload` (reads CASPAR_DB)."""
    import os
    from config_assessment.api.app import create_app
    db_path = os.environ.get("CASPAR_DB", "ccss.db")
    app = create_app(db_path=db_path)
    _mount_frontend(app)
    return app
