"""
tests/test_init_cmds.py
-----------------------
`caspar init` — restoring the working DB from the dump shipped in the package.

This is the command that makes a `pip install cvm-caspar` usable: a pip install
has no repository, so data/ccss_canonical.sql is out of reach and every scan
would stop at "DB not found". The risks worth testing are that the shipped dump
silently drifts from the repository's copy, and that a restore destroys a
working DB that holds scan history the dump does not contain.
"""

from __future__ import annotations

import gzip
import sqlite3
from pathlib import Path

from click.testing import CliRunner

import cli.commands.init_cmds as ic

REPO = Path(__file__).resolve().parents[1]


class TestShippedDump:
    def test_the_packaged_dump_matches_the_repository_source(self):
        """The wheel's copy is generated from data/ccss_canonical.sql.

        Nothing regenerates it automatically, so an update to the canonical SQL
        that forgets the gzip would ship a stale knowledge base to every pip
        user while the repository and the Docker image are correct — a
        divergence that produces different scores for the same input, which is
        precisely the property CVM claims to guarantee.
        """
        source = (REPO / "data" / "ccss_canonical.sql").read_bytes()
        shipped = gzip.open(ic.canonical_dump(), "rb").read()
        assert shipped == source, (
            "config_assessment/core/db/ccss_canonical.sql.gz is out of date. "
            "Regenerate it: gzip -9 -c data/ccss_canonical.sql > "
            "config_assessment/core/db/ccss_canonical.sql.gz"
        )

    def test_the_dump_is_inside_the_python_package(self):
        """It must sit under config_assessment/, not at the repository root.

        `packages = ["config_assessment", "cli"]` is what hatchling copies into
        the wheel; a file at the root would be present in a source checkout and
        missing once installed — working in every test and failing only for the
        users this command exists for.
        """
        dump = ic.canonical_dump()
        assert dump.is_file()
        assert "config_assessment" in dump.parts


class TestInit:
    def _run(self, tmp_path: Path, *args: str):
        db = tmp_path / "ccss.db"
        res = CliRunner().invoke(ic.init, list(args), obj={"db_path": str(db)})
        return res, db

    def test_it_creates_a_usable_knowledge_base(self, tmp_path):
        res, db = self._run(tmp_path)
        assert res.exit_code == 0, res.output
        assert db.is_file()

        conn = sqlite3.connect(str(db))
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM misconfigurations").fetchone()[0]
            targets = conn.execute(
                "SELECT COUNT(DISTINCT target_name) FROM misconfigurations"
            ).fetchone()[0]
        finally:
            conn.close()
        # The point of the command is a DB that can actually assess something;
        # asserting only that the file exists would pass on an empty database.
        assert count > 100, f"only {count} misconfigurations restored"
        assert targets >= 7, f"only {targets} targets restored"

    def test_an_existing_db_is_never_silently_replaced(self, tmp_path):
        """The working DB holds scan history and user-installed plugins, none
        of which is in the dump. Overwriting it on a stray `caspar init` would
        destroy them with no warning and no way back."""
        res, db = self._run(tmp_path)
        assert res.exit_code == 0

        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE user_marker (x INTEGER)")
        conn.commit()
        conn.close()

        again, _ = self._run(tmp_path)
        assert again.exit_code == 1
        assert "already exists" in again.output

        conn = sqlite3.connect(str(db))
        try:
            survived = conn.execute(
                "SELECT name FROM sqlite_master WHERE name='user_marker'"
            ).fetchone()
        finally:
            conn.close()
        assert survived is not None, "the existing DB was replaced anyway"

    def test_force_replaces_it(self, tmp_path):
        res, db = self._run(tmp_path)
        assert res.exit_code == 0
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE user_marker (x INTEGER)")
        conn.commit()
        conn.close()

        forced, _ = self._run(tmp_path, "--force")
        assert forced.exit_code == 0
        conn = sqlite3.connect(str(db))
        try:
            gone = conn.execute(
                "SELECT name FROM sqlite_master WHERE name='user_marker'"
            ).fetchone()
        finally:
            conn.close()
        assert gone is None, "--force did not replace the database"

    def test_a_failed_restore_leaves_no_half_written_db(self, tmp_path):
        """Restore writes to a temporary file and moves it into place, so an
        interrupted run cannot leave a partial DB that later scans would read
        as if it were complete."""
        db = tmp_path / "ccss.db"
        broken = tmp_path / "broken.sql.gz"
        with gzip.open(broken, "wt", encoding="utf-8") as fh:
            fh.write("CREATE TABLE ok (x INTEGER); ")
            fh.write("THIS IS NOT SQL;")

        try:
            ic.restore_from_dump(db, broken)
        except sqlite3.Error:
            pass
        else:
            raise AssertionError("expected the malformed dump to fail")

        assert not db.exists(), "a failed restore left a database behind"
        leftovers = list(tmp_path.glob("*.db"))
        assert leftovers == [], f"temporary files left behind: {leftovers}"
