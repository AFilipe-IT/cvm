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
    Swagger UI:   http://127.0.0.1:2027/docs
    CVM Console:  http://127.0.0.1:2027/app
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
    # Announcing the console unconditionally sent people to a URL that 404s
    # when the bundle isn't there. The mount is soft-failing by design, so the
    # startup line is the only place the absence can be reported.
    if _console_dist().is_dir():
        click.echo(click.style(f"  CVM Console: http://{host}:{port}/app", fg="cyan"))
    else:
        click.echo(click.style(
            "  CVM Console: unavailable — the frontend bundle is missing.\n"
            "               Reinstall (./install-native.sh) or use the Docker "
            "image, which ships it.", fg="yellow"))
    # v2 is announced only when built. Its dist is not committed, so staying
    # silent is the common case and printing a URL that 404s would be worse
    # than saying nothing about a console the user may not be working on.
    if _console_v2_dist().is_dir():
        click.echo(click.style(f"  CVM Console (v2): http://{host}:{port}/v2/app",
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
    """Where the built console lives, for both the mount and the startup line.

    One function so `serve` cannot advertise a console the mount then declines
    to serve — the two used to derive the path independently."""
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _console_v2_dist() -> Path:
    """The v2 console's bundle.

    Served at its own prefix rather than replacing v1. v1 is what the
    validated artefact ships and what every existing link and document points
    at, so moving /app is a product decision rather than a build detail; the
    two run side by side until that decision is taken. The prefix is also why
    v2 must be built with `--base=/v2/app/` — a bundle built for one prefix
    requests its assets from that prefix wherever it is actually mounted."""
    return Path(__file__).resolve().parents[2] / "frontend-v2" / "dist"


def _mount_frontend(app) -> None:
    """Mount the built React consoles: v1 at /app, v2 at /v2/app.

    v1's bundle is committed to the repository and the Docker image builds its
    own, so in both supported installations it is there. Soft-failing covers
    the remaining case — a source tree whose dist was cleaned — where the REST
    API is still useful on its own; `serve` reports the absence on startup.
    v2's dist is NOT committed, so its mount is absent far more often than
    v1's; that is the same soft-fail, not a different policy.

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

    # v2 first: Starlette matches mounts in registration order, and /app is a
    # prefix of nothing here, but registering the more specific path first
    # keeps that independent of how the prefixes later change.
    if _console_v2_dist().is_dir():
        app.mount("/v2/app",
                  SpaStaticFiles(directory=str(_console_v2_dist()), html=True),
                  name="cvm-console-v2")
    if _console_dist().is_dir():
        app.mount("/app", SpaStaticFiles(directory=str(_console_dist()), html=True),
                  name="cvm-console")


def _reload_app():
    """Factory target for `uvicorn --reload` (reads CASPAR_DB)."""
    import os
    from config_assessment.api.app import create_app
    db_path = os.environ.get("CASPAR_DB", "ccss.db")
    app = create_app(db_path=db_path)
    _mount_frontend(app)
    return app
