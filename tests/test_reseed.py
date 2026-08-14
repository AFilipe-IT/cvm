"""
tests/test_reseed.py
--------------------
Versioned built-in refresh: when the image ships a newer base DB, an existing
volume's built-in targets are updated while user-installed plugins are kept.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from config_assessment.core.db.reseed import (
    refresh_builtins_if_stale, BASE_DB_VERSION, BUILTIN_TARGETS)

CANONICAL = Path("data/ccss_canonical.sql")


def _seed_db(path):
    sqlite3.connect(str(path)).executescript(CANONICAL.read_text())


def _add_user_plugin(conn, name="mongodb"):
    tid = conn.execute(
        "INSERT INTO targets(name,display_name,version,benchmark_source) "
        "VALUES(?,?,?,?)", (name, name.title(), "1.0", "STIG")).lastrowid
    conn.execute(
        "INSERT INTO attack_chains(target_id,target_name,chain_id,"
        "misconfig_directives,amplification,justification) "
        "VALUES(?,?,?,?,?,?)", (tid, name, f"{name}-chain", "[]", 1.5, "user"))
    conn.commit()


@pytest.fixture
def seed(tmp_path):
    p = tmp_path / "seed.db"
    _seed_db(p)
    return p


def test_fresh_seed_is_already_current(seed, tmp_path):
    # A DB just copied from seed carries the current version → no refresh.
    work = tmp_path / "work.db"
    work.write_bytes(seed.read_bytes())
    assert refresh_builtins_if_stale(work, seed) is False


def test_stale_volume_gets_builtins_refreshed(seed, tmp_path):
    work = tmp_path / "work.db"
    work.write_bytes(seed.read_bytes())
    conn = sqlite3.connect(str(work))
    # Simulate an OLD volume: stale justification + no version stamp.
    conn.execute("UPDATE attack_chains SET justification='OLD privilege escalation' "
                 "WHERE chain_id='load-module-status-userdir'")
    conn.execute("DELETE FROM caspar_meta")           # pretend pre-versioning
    conn.commit(); conn.close()

    assert refresh_builtins_if_stale(work, seed) is True

    conn = sqlite3.connect(str(work))
    j = conn.execute("SELECT justification FROM attack_chains "
                     "WHERE chain_id='load-module-status-userdir'").fetchone()[0]
    assert "OLD privilege escalation" not in j        # refreshed from seed
    ver = conn.execute("SELECT value FROM caspar_meta "
                       "WHERE key='base_db_version'").fetchone()[0]
    assert int(ver) == BASE_DB_VERSION
    conn.close()


def test_refresh_preserves_user_plugins(seed, tmp_path):
    work = tmp_path / "work.db"
    work.write_bytes(seed.read_bytes())
    conn = sqlite3.connect(str(work))
    conn.execute("DELETE FROM caspar_meta")           # force stale
    _add_user_plugin(conn, "mongodb")
    conn.close()

    refresh_builtins_if_stale(work, seed)

    conn = sqlite3.connect(str(work))
    assert conn.execute("SELECT COUNT(*) FROM targets WHERE name='mongodb'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM attack_chains "
                        "WHERE target_name='mongodb'").fetchone()[0] == 1
    # Built-ins are all still present too.
    n = conn.execute("SELECT COUNT(DISTINCT target_name) FROM misconfigurations "
                     "WHERE target_name IN (%s)" %
                     ",".join("?" * len(BUILTIN_TARGETS)), BUILTIN_TARGETS).fetchone()[0]
    assert n == len(BUILTIN_TARGETS)
    conn.close()


def test_idempotent(seed, tmp_path):
    work = tmp_path / "work.db"
    work.write_bytes(seed.read_bytes())
    conn = sqlite3.connect(str(work)); conn.execute("DELETE FROM caspar_meta"); conn.commit(); conn.close()
    assert refresh_builtins_if_stale(work, seed) is True    # first: refreshes
    assert refresh_builtins_if_stale(work, seed) is False   # second: no-op


def test_missing_files_are_safe(tmp_path):
    assert refresh_builtins_if_stale(tmp_path / "nope.db", tmp_path / "no-seed.db") is False


class TestBuiltinsMatchTheDump:
    """BUILTIN_TARGETS and the dump must name the same targets.

    These two are edited in different commits — a plugin is built and the dump
    regenerated, the tuple is forgotten — and nothing here used to compare them:
    the refresh test asserted the tuple against itself, so a built-in missing
    from the tuple passed every test while never reaching a single existing
    volume. postgresql spent from 1 Aug to 14 Aug 2026 in exactly that state,
    its plugin code in every install and its 26 rules in none, reporting "0
    rules · NOT ASSESSED" to anyone who scanned a PostgreSQL config from Docker
    or pip.
    """

    def _dump_targets(self, seed) -> set[str]:
        conn = sqlite3.connect(str(seed))
        try:
            return {r[0] for r in conn.execute("SELECT name FROM targets")}
        finally:
            conn.close()

    def test_every_target_in_the_dump_is_declared_builtin(self, seed):
        missing = self._dump_targets(seed) - set(BUILTIN_TARGETS)
        assert not missing, (
            f"in data/ccss_canonical.sql but not in BUILTIN_TARGETS: "
            f"{sorted(missing)}. They ship in the image and are never "
            f"refreshed into an existing volume — add them to the tuple in "
            f"config_assessment/core/db/reseed.py.")

    def test_every_declared_builtin_is_in_the_dump(self, seed):
        """The other direction: a name in the tuple with no rows in the dump
        makes the refresh delete that target's rules from a working DB and put
        nothing back."""
        missing = set(BUILTIN_TARGETS) - self._dump_targets(seed)
        assert not missing, (
            f"in BUILTIN_TARGETS but not in data/ccss_canonical.sql: "
            f"{sorted(missing)}. A refresh would delete their rules and "
            f"restore nothing.")

    def test_the_declared_version_matches_the_dump(self, seed):
        """BASE_DB_VERSION below the dump's means the refresh never fires;
        above it means it fires on every start."""
        conn = sqlite3.connect(str(seed))
        try:
            stamped = int(conn.execute(
                "SELECT value FROM caspar_meta "
                "WHERE key='base_db_version'").fetchone()[0])
        finally:
            conn.close()
        assert stamped == BASE_DB_VERSION

    def test_a_refreshed_volume_can_actually_use_a_new_builtin(self, seed, tmp_path):
        """End-to-end for the postgresql case: a volume that predates a
        built-in must come out of the refresh with its targets row and its
        rules, not just one of the two — `caspar targets` reads the row, the
        scan reads the rules, and a target with only one of them is broken in a
        way neither table's own count reveals."""
        work = tmp_path / "work.db"
        work.write_bytes(seed.read_bytes())
        conn = sqlite3.connect(str(work))
        # An old volume: postgresql had not been built yet, so neither its
        # target row nor its rules exist, and the version predates it.
        conn.execute("DELETE FROM misconfigurations WHERE target_name='postgresql'")
        conn.execute("DELETE FROM attack_chains WHERE target_name='postgresql'")
        conn.execute("DELETE FROM targets WHERE name='postgresql'")
        conn.execute("DELETE FROM caspar_meta")
        conn.commit()
        conn.close()

        assert refresh_builtins_if_stale(work, seed) is True

        conn = sqlite3.connect(str(work))
        try:
            row = conn.execute(
                "SELECT id FROM targets WHERE name='postgresql'").fetchone()
            assert row is not None, "the target row was not restored"
            rules = conn.execute(
                "SELECT COUNT(*) FROM misconfigurations "
                "WHERE target_name='postgresql'").fetchone()[0]
            assert rules > 0, "the rules were not restored"
            # The rules must point at the row that is actually there, or the
            # target resolves to nothing at scan time.
            orphans = conn.execute(
                "SELECT COUNT(*) FROM misconfigurations "
                "WHERE target_name='postgresql' AND target_id != ?",
                (row[0],)).fetchone()[0]
            assert orphans == 0, f"{orphans} rules point at a different target_id"
        finally:
            conn.close()


class TestCanonicalShipsNoScans:
    """A fresh install starts with an empty history.

    The canonical dump used to carry 54 development scans, so the console's
    Dashboard showed scores, findings and attack chains to someone who had
    never run an assessment — and any number a user took from that screen
    silently mixed their own results with ours. The knowledge base (rules,
    chains, targets) is the product and must stay; the scan history is not.
    """

    def test_no_scan_results_in_the_canonical_dump(self, seed):
        conn = sqlite3.connect(str(seed))
        assert conn.execute("SELECT COUNT(*) FROM scan_results").fetchone()[0] == 0

    def test_the_knowledge_base_is_still_there(self, seed):
        """The counterpart assertion: stripping scans must not strip content."""
        conn = sqlite3.connect(str(seed))
        misconfigs = conn.execute("SELECT COUNT(*) FROM misconfigurations").fetchone()[0]
        chains = conn.execute("SELECT COUNT(*) FROM attack_chains").fetchone()[0]
        targets = conn.execute("SELECT COUNT(*) FROM targets").fetchone()[0]
        assert misconfigs > 400
        assert chains > 20
        assert targets >= 11

    def test_the_first_user_scan_gets_id_one(self, seed):
        """sqlite_sequence must not remember the stripped rows.

        Leaving scan_results' sequence behind would start a user's first scan
        at id 55 — harmless in effect, but it is a leftover of data that is no
        longer there, and it shows in URLs.
        """
        conn = sqlite3.connect(str(seed))
        row = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='scan_results'").fetchone()
        assert row is None
