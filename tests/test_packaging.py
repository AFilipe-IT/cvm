"""
tests/test_packaging.py
-----------------------
The wheel's force-include entries and the Dockerfile that has to satisfy them.

pyproject.toml force-includes both consoles' dist directories, because a pip
install has no repository to obtain a console from. hatchling treats a missing
forced include as a hard error, not a warning — so every install path that runs
`pip install -e .` must have those directories on disk at that moment.

That is not automatic. .dockerignore deliberately excludes both dist/ trees so
the image builds them from source rather than shipping a developer's local copy,
and the image restores them with COPY --from. When the install ran before that
COPY, the build died with

    FileNotFoundError: Forced include not found: /home/caspar/app/frontend-v2/dist

which is a failure only a full Docker build reveals — several minutes in, and
only if someone happens to rebuild. These tests state the ordering as a fact
about the files instead.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO / "docker" / "caspar" / "Dockerfile"


def _forced_includes() -> dict[str, str]:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return (data["tool"]["hatch"]["build"]["targets"]["wheel"]
            .get("force-include", {}))


class TestForcedIncludes:
    def test_both_consoles_are_forced_into_the_wheel(self):
        """Without these the wheel installs a `caspar serve` that hosts the
        REST API and no console at all — and, having no repository, no way to
        obtain one."""
        assert _forced_includes() == {
            "frontend-v2/dist": "frontend-v2/dist",
            "frontend/dist": "frontend/dist",
        }

    def test_every_forced_include_exists_in_the_repository(self):
        """An editable install fails outright on a forced include that is not
        there, so a path that is renamed here and not on disk breaks
        install-native.sh for everyone, not just the wheel."""
        for src in _forced_includes():
            assert (REPO / src).is_dir(), (
                f"pyproject.toml force-includes {src!r}, which does not exist. "
                f"`pip install -e .` raises FileNotFoundError on this, so the "
                f"native installer and the Docker build both fail.")

    def test_the_wheel_targets_match_where_serve_looks_for_them(self):
        """The destination paths mirror the source tree because that is where
        _mount_frontend resolves them: <package-root>/frontend*/dist, which is
        the repository root in a checkout and site-packages in a wheel."""
        import cli.commands.serve_cmds as sc

        wheel_paths = set(_forced_includes().values())
        for dist in (sc._console_dist(), sc._console_v2_dist()):
            rel = dist.relative_to(REPO).as_posix()
            assert rel in wheel_paths, (
                f"serve looks in {rel}, which the wheel does not ship")


class TestLicence:
    """Apache-2.0, declared the way current PyPI expects it.

    Without a licence PyPI shows the package as unlicensed, which legally means
    all rights reserved — the metadata is what actually grants anyone the right
    to use this, so it is worth asserting rather than assuming.
    """

    def _project(self) -> dict:
        data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        return data["project"]

    def test_the_licence_files_exist_and_are_declared(self):
        proj = self._project()
        assert proj["license"] == "Apache-2.0"
        # NOTICE is not optional decoration: Apache-2.0 §4(d) requires it to
        # travel with the work, and it carries the CIS/DISA/NIST provenance.
        assert proj["license-files"] == ["LICENSE", "NOTICE"]
        for name in proj["license-files"]:
            assert (REPO / name).is_file(), f"{name} is declared but missing"

    def test_the_licence_text_is_the_unmodified_apache_2_0(self):
        """Byte-identical to the text at apache.org/licenses/LICENSE-2.0.txt.

        A licence edited by accident (a stray reformat, a find-and-replace over
        the tree) is no longer the licence it names, and nothing else in the
        repository would notice.
        """
        import hashlib

        digest = hashlib.sha256(
            (REPO / "LICENSE").read_bytes()).hexdigest()
        assert digest == (
            "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
        ), "LICENSE is not the canonical Apache 2.0 text"

    def test_no_legacy_license_classifier(self):
        """PEP 639 deprecates `License ::` classifiers alongside a license
        expression, and PyPI rejects an upload that carries both."""
        bad = [c for c in self._project()["classifiers"]
               if c.startswith("License ::")]
        assert not bad, f"remove the deprecated classifier(s): {bad}"

    def test_the_sdist_ships_them(self):
        data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        include = data["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
        for name in ("LICENSE", "NOTICE"):
            assert name in include, (
                f"{name} is missing from the sdist include list — the wheel "
                f"carries it via license-files, the sdist does not.")


class TestVersion:
    """`caspar --version` and the version the package declares must agree.

    They come from different places — pyproject.toml is read by the build
    backend, CASPAR_VERSION by the CLI and by every scan's reproducibility
    manifest — so nothing but a test stops a release bumping one and not the
    other. A scan claiming `caspar 1.0.0` from a 1.1.0 install is a
    reproducibility record that points at the wrong code.
    """

    def test_the_cli_reports_the_declared_version(self):
        from click.testing import CliRunner

        from cli.main import cli

        r = CliRunner().invoke(cli, ["--version"])
        assert r.exit_code == 0, r.output
        assert r.output.strip() == f"caspar {self._declared()}"

    def test_the_manifest_constant_matches_pyproject(self):
        from config_assessment.core.manifest import CASPAR_VERSION

        assert CASPAR_VERSION == self._declared(), (
            f"pyproject.toml says {self._declared()} but the manifest stamps "
            f"{CASPAR_VERSION} into every scan result")

    @staticmethod
    def _declared() -> str:
        data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        return data["project"]["version"]


class TestDockerfileSatisfiesThem:
    """The image is the one install path where the dists are absent by design."""

    def _lines(self) -> list[str]:
        return DOCKERFILE.read_text(encoding="utf-8").splitlines()

    def _index_of(self, pattern: str) -> int:
        rx = re.compile(pattern)
        for i, line in enumerate(self._lines()):
            if rx.search(line):
                return i
        raise AssertionError(f"no line in the Dockerfile matches {pattern!r}")

    def test_the_consoles_are_copied_before_the_editable_install(self):
        """The ordering that the FileNotFoundError above is about.

        .dockerignore keeps frontend/dist and frontend-v2/dist out of the build
        context on purpose, so between `COPY . .` and these two COPY --from
        lines the forced includes simply are not there.
        """
        install = self._index_of(r"pip install .*-e \.")
        for stage in ("console", "console-v2"):
            copied = self._index_of(rf"COPY --from={stage} .*dist")
            assert copied < install, (
                f"the {stage} dist is copied at line {copied + 1}, after the "
                f"editable install at line {install + 1}. hatchling fails the "
                f"build on the missing forced include.")

    def test_the_dists_are_still_kept_out_of_the_build_context(self):
        """The counterpart: if .dockerignore stopped excluding them the image
        would ship whatever the developer had on disk instead of what its own
        stages built, and the test above would pass for the wrong reason."""
        ignored = (REPO / ".dockerignore").read_text(encoding="utf-8").split()
        for path in ("frontend/dist/", "frontend-v2/dist/"):
            assert path in ignored, (
                f"{path} is no longer excluded in .dockerignore — the image "
                f"would ship the committed bundle rather than building it.")
