"""
tests/test_serve_cmds.py
------------------------
`caspar serve` — what it tells the user about the CVM Console on startup.

Both console bundles (frontend/dist, frontend-v2/dist) are committed to the
repository and rebuilt independently inside the Docker image, so in every
supported installation they are present. The mount soft-fails when one isn't,
which used to mean `serve` printed a console URL that answered 404 — the startup
banner is the only place that absence can surface, so it is worth a test of its
own.

v2 is the primary console and answers at /app; v1 moved to /v1/app when v2 was
promoted. Each bundle must therefore be built for a different prefix than before,
which is asserted directly against the committed artefacts below.
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

    def test_the_v2_bundle_is_committed_too(self):
        """Same guarantee for v2, which is versioned for the same reason."""
        index = sc._console_v2_dist() / "index.html"
        assert index.is_file(), (
            "frontend-v2/dist/index.html is missing — native installs would "
            "have no v2 console. Rebuild with `npm run build` in frontend-v2/."
        )

    def test_each_bundle_was_built_for_the_prefix_it_is_mounted_at(self):
        """A bundle built for one prefix requests its assets from that prefix
        wherever it is actually mounted, so a dist built with the wrong base
        loads a blank page and 404s on every asset. This is the one build
        mistake that survives a green `npm run build`, which is why it is
        asserted against the committed artefacts rather than trusted.

        Both are checked: promoting v2 to /app moved v1 to /v1/app, so the
        prefix each was built for changed at the same time and a stale bundle
        of either one is the failure this catches.
        """
        for dist, prefix, folder in (
            (sc._console_v2_dist(), "/app", "frontend-v2"),
            (sc._console_dist(), "/v1/app", "frontend"),
        ):
            html = (dist / "index.html").read_text(encoding="utf-8")
            assert f'"{prefix}/assets/' in html, (
                f"{folder}/dist was built with the wrong base — it is mounted "
                f"at {prefix}. Rebuild with `npm run build` in {folder}/ "
                f"(vite.config.ts pins the base); do not override CVM_BASE for "
                f"a committed build."
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
        """/app is v2's, so the primary URL depends on v2's bundle."""
        dist = tmp_path / "frontend" / "dist"
        v2 = tmp_path / "frontend-v2" / "dist"
        dist.mkdir(parents=True)
        v2.mkdir(parents=True)
        out = self._banner(monkeypatch, dist, v2_dist=v2)
        assert ":2027/app" in out
        assert "unavailable" not in out

    def test_absence_is_reported_instead_of_a_dead_url(self, tmp_path, monkeypatch):
        """With v2 absent, /app has nothing to serve and must not be printed."""
        dist = tmp_path / "frontend" / "dist"
        dist.mkdir(parents=True)
        out = self._banner(monkeypatch, dist)   # v2 path deliberately absent
        assert "unavailable" in out
        # No /app URL to click: that link would have 404'd. Matched with the
        # host prefix rather than as a bare "/app" substring, which /v1/app
        # also contains — the loose form would pass on v1's line alone.
        assert ":2027/app" not in out
        # The API is unaffected and must still be advertised.
        assert "/docs" in out

    def test_both_consoles_are_announced_at_their_own_prefixes(self, tmp_path, monkeypatch):
        """Both consoles are served side by side, each at its own prefix."""
        dist = tmp_path / "frontend" / "dist"
        v2 = tmp_path / "frontend-v2" / "dist"
        dist.mkdir(parents=True)
        v2.mkdir(parents=True)
        out = self._banner(monkeypatch, dist, v2_dist=v2)
        assert ":2027/app" in out
        assert ":2027/v1/app" in out

    def test_v1_is_silent_when_not_built(self, tmp_path, monkeypatch):
        """v1 is the secondary console now; announcing a URL that 404s would be
        worse than saying nothing about a console the user may not want."""
        v2 = tmp_path / "frontend-v2" / "dist"
        v2.mkdir(parents=True)
        missing_v1 = tmp_path / "frontend" / "dist"   # deliberately not created
        missing_v1.parent.mkdir(parents=True)         # _banner puts the db here
        out = self._banner(monkeypatch, missing_v1, v2_dist=v2)
        assert ":2027/app" in out
        assert "/v1/app" not in out
