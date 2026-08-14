"""
tests/test_serve_cmds.py
------------------------
`caspar serve` — what it tells the user about the CVM Console on startup.

The console bundle (frontend/dist) is committed to the repository and rebuilt
independently inside the Docker image, so in both supported installations it is
present. The mount soft-fails when it isn't, which used to mean `serve` printed
a console URL that answered 404 — the startup banner is the only place that
absence can surface, so it is worth a test of its own.
"""

from __future__ import annotations

from pathlib import Path

import cli.commands.serve_cmds as sc


class TestConsoleDistIsShared:
    def test_mount_and_banner_agree_on_the_path(self):
        """One source of truth, so serve cannot advertise what the mount skips.

        The two used to derive the location independently; a divergence would
        reintroduce exactly the 404 this module exists to prevent.
        """
        dist = sc._console_dist()
        assert dist.name == "dist"
        assert dist.parent.name == "frontend"

    def test_the_committed_bundle_is_actually_there(self):
        """A clone must serve the console with no Node toolchain installed.

        frontend/dist is versioned for this reason (see frontend/.gitignore).
        If a rebuild or a stray clean drops index.html, native installs go back
        to having no console — silently, since the mount soft-fails.
        """
        index = sc._console_dist() / "index.html"
        assert index.is_file(), (
            "frontend/dist/index.html is missing — native installs would have "
            "no web console. Rebuild with `npm run build` in frontend/."
        )


class TestStartupBanner:
    """The banner must track reality, not assume the bundle is present."""

    def _banner(self, monkeypatch, dist: Path, v2_dist: Path | None = None) -> str:
        """Run serve's banner alone: uvicorn.run and create_app never fire.

        Invoking the command for real would bind a port and block, so the two
        heavy calls are stubbed and the DB check is satisfied by a real file.

        BOTH console paths are redirected into the tmp tree. Leaving v2 pointing
        at the real repository made these tests depend on whether someone had
        run `npm run build` in frontend-v2 — they passed on a clean checkout and
        failed once the bundle existed, which is a test reporting the developer's
        working directory rather than the behaviour under test.
        """
        import click
        from click.testing import CliRunner

        monkeypatch.setattr(sc, "_console_dist", lambda: dist)
        monkeypatch.setattr(
            sc, "_console_v2_dist",
            lambda: v2_dist if v2_dist is not None else dist.parent / "no-v2-here")

        lines: list[str] = []
        # serve() imports uvicorn inside the function body, so patching the
        # module attribute here would be too late — stub the run call instead
        # via a sentinel exception that unwinds right after the banner.
        class _Stop(click.ClickException):
            pass

        import sys
        import types
        fake_uvicorn = types.ModuleType("uvicorn")
        fake_uvicorn.run = lambda *a, **k: (_ for _ in ()).throw(_Stop("stopped"))
        monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
        monkeypatch.setattr(
            "config_assessment.api.app.create_app", lambda **kw: object())
        monkeypatch.setattr(sc, "_mount_frontend", lambda app: None)

        db = dist.parent / "ccss.db"
        db.write_text("")   # existence is all serve checks before the banner

        res = CliRunner().invoke(sc.serve, obj={"db_path": str(db)})
        del lines
        return res.output

    def test_console_url_shown_when_the_bundle_exists(self, tmp_path, monkeypatch):
        dist = tmp_path / "frontend" / "dist"
        dist.mkdir(parents=True)
        out = self._banner(monkeypatch, dist)
        assert "/app" in out
        assert "unavailable" not in out

    def test_absence_is_reported_instead_of_a_dead_url(self, tmp_path, monkeypatch):
        dist = tmp_path / "frontend" / "dist"     # deliberately not created
        dist.parent.mkdir(parents=True)
        out = self._banner(monkeypatch, dist)
        assert "unavailable" in out
        # No console URL to click: that link would have 404'd. Matched with the
        # host prefix rather than as a bare "/app" substring, which /v2/app also
        # contains — the loose form passed only because v2 happened to be absent.
        assert ":2027/app" not in out
        # The API is unaffected and must still be advertised.
        assert "/docs" in out

    def test_v2_is_announced_at_its_own_prefix_when_built(self, tmp_path, monkeypatch):
        """Both consoles are served side by side, each at its own prefix."""
        dist = tmp_path / "frontend" / "dist"
        v2 = tmp_path / "frontend-v2" / "dist"
        dist.mkdir(parents=True)
        v2.mkdir(parents=True)
        out = self._banner(monkeypatch, dist, v2_dist=v2)
        assert ":2027/app" in out
        assert ":2027/v2/app" in out

    def test_v2_is_silent_when_not_built(self, tmp_path, monkeypatch):
        """v2's dist is not committed, so its absence is the common case.

        Announcing a URL that 404s would be worse than saying nothing about a
        console the user may not be working on at all.
        """
        dist = tmp_path / "frontend" / "dist"
        dist.mkdir(parents=True)
        out = self._banner(monkeypatch, dist)   # v2 path deliberately absent
        assert ":2027/app" in out
        assert "/v2/app" not in out
