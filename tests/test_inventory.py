"""
tests/test_inventory.py
-----------------------
Tests for host identity (the UUID) and attribute collection.

The point under test throughout is the separation between identity and
attributes: a host that gets renamed, re-addressed or upgraded must remain the
same host, and its scan history must stay attached to it.
"""

from __future__ import annotations

import sqlite3

import pytest

from config_assessment.core.db.database import Database
from config_assessment.core.inventory import HostAttributes, collect, _read_os_release


@pytest.fixture
def db(tmp_path):
    with Database(tmp_path / "t.db") as d:
        yield d


# ── identity ───────────────────────────────────────────────────────────

def test_first_registration_mints_a_uuid(db):
    host = db.get_host(db.upsert_host("web01"))
    assert host["uuid"]
    assert len(host["uuid"]) == 36  # canonical uuid4 form


def test_re_registering_keeps_the_same_identity(db):
    first = db.upsert_host("web01")
    original = db.get_host(first)["uuid"]
    again = db.upsert_host("web01")
    assert again == first
    assert db.get_host(again)["uuid"] == original, \
        "a repeat scan under the same label must not mint a new identity"


def test_distinct_hosts_get_distinct_uuids(db):
    a = db.get_host(db.upsert_host("web01"))["uuid"]
    b = db.get_host(db.upsert_host("web02"))["uuid"]
    assert a != b


def test_uuid_is_unique_at_the_schema_level(db):
    db.upsert_host("web01")
    dup = db.get_host(db.upsert_host("web02"))["uuid"]
    with pytest.raises(sqlite3.IntegrityError):
        db._conn.execute("UPDATE hosts SET uuid = ? WHERE label = 'web01'", (dup,))


def test_a_renamed_host_keeps_its_identity_and_its_scans(db):
    """The reason the UUID exists: renaming must not split the history."""
    host_id = db.upsert_host("web01")
    identity = db.get_host(host_id)["uuid"]

    db.rename_host(host_id, "web01.prod.example")

    assert db.get_host(host_id)["uuid"] == identity
    assert db.get_host_by_uuid(identity)["label"] == "web01.prod.example"
    # And the old label no longer resolves — it is genuinely gone, not aliased.
    assert db.get_host_id("web01") is None


def test_lookup_by_uuid_survives_the_rename(db):
    host_id = db.upsert_host("web01")
    identity = db.get_host(host_id)["uuid"]
    db.rename_host(host_id, "renamed")
    assert db.get_host_by_uuid(identity)["id"] == host_id


def test_unknown_lookups_return_none(db):
    assert db.get_host(999) is None
    assert db.get_host_by_uuid("nope") is None


# ── attributes ─────────────────────────────────────────────────────────

def test_a_fresh_host_has_no_attributes_yet(db):
    """NULL means 'never inspected' — distinct from 'inspected, found empty'."""
    host = db.get_host(db.upsert_host("web01"))
    assert host["hostname"] is None
    assert host["last_seen_at"] is None


def test_updating_attributes_stamps_last_seen(db):
    host_id = db.upsert_host("web01")
    db.update_host_attributes(host_id, hostname="web01.local", os_family="ubuntu")
    host = db.get_host(host_id)
    assert host["hostname"] == "web01.local"
    assert host["os_family"] == "ubuntu"
    assert host["last_seen_at"] is not None


def test_an_omitted_attribute_is_left_untouched(db):
    host_id = db.upsert_host("web01")
    db.update_host_attributes(host_id, hostname="web01.local", kernel="5.15.0")
    db.update_host_attributes(host_id, ip_address="10.0.0.5")
    host = db.get_host(host_id)
    assert host["kernel"] == "5.15.0", "an unrelated update must not blank it"
    assert host["ip_address"] == "10.0.0.5"


def test_an_explicit_none_retracts_the_attribute(db):
    """collect() returns None for what it cannot observe, so passing None must
    clear the field rather than leave a stale value standing — otherwise a
    host keeps advertising an address it no longer has."""
    host_id = db.upsert_host("web01")
    db.update_host_attributes(host_id, hostname="web01.local")
    assert db.get_host(host_id)["hostname"] == "web01.local"

    db.update_host_attributes(host_id, hostname=None)
    assert db.get_host(host_id)["hostname"] is None


def test_collecting_from_a_mounted_root_retracts_unobservable_fields(db, tmp_path):
    """The case that matters in practice: scanning a mounted target must not
    leave the collector's own hostname attached to that host."""
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/os-release").write_text('ID=ubuntu\nVERSION_ID="22.04"\n')

    host_id = db.upsert_host("target")
    db.update_host_attributes(host_id, **collect().as_dict())
    assert db.get_host(host_id)["hostname"], "local collection sees a hostname"

    db.update_host_attributes(host_id, **collect(root=tmp_path).as_dict())
    host = db.get_host(host_id)
    assert host["os_version"] == "22.04", "the target's OS is recorded"
    assert host["hostname"] is None, \
        "the collector's hostname must not be attributed to the target"


def test_identity_is_not_writable_through_the_attribute_path(db):
    host_id = db.upsert_host("web01")
    identity = db.get_host(host_id)["uuid"]
    db.update_host_attributes(host_id, uuid="attacker-chosen", label="renamed")
    host = db.get_host(host_id)
    assert host["uuid"] == identity
    assert host["label"] == "web01"


def test_updating_nothing_is_a_no_op(db):
    host_id = db.upsert_host("web01")
    db.update_host_attributes(host_id)
    assert db.get_host(host_id)["last_seen_at"] is None


# ── collection ─────────────────────────────────────────────────────────

def test_collect_describes_the_running_system():
    attrs = collect()
    assert attrs.hostname
    assert attrs.kernel
    assert attrs.os_family


def test_os_release_is_parsed_with_and_without_quotes(tmp_path):
    f = tmp_path / "os-release"
    f.write_text('NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="22.04"\n')
    assert _read_os_release(f) == ("ubuntu", "22.04")


def test_a_malformed_line_does_not_cost_the_parseable_ones(tmp_path):
    f = tmp_path / "os-release"
    f.write_text('ID=ubuntu\nthis is not an assignment\n# a comment\nVERSION_ID=22.04\n')
    assert _read_os_release(f) == ("ubuntu", "22.04")


def test_a_missing_os_release_yields_none_not_a_crash(tmp_path):
    assert _read_os_release(tmp_path / "absent") == (None, None)


def test_collect_against_a_mounted_root_reads_that_system(tmp_path):
    """Scanning a mounted target must describe the target, not the container."""
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/os-release").write_text('ID=debian\nVERSION_ID="12"\n')

    attrs = collect(root=tmp_path)
    assert (attrs.os_family, attrs.os_version) == ("debian", "12")
    # hostname, ip and kernel belong to the RUNNING system, which is not the
    # mounted one. Reporting the collector's own values here would attribute
    # this machine's identity to a different host — silently and wrongly.
    assert attrs.kernel is None
    assert attrs.hostname is None
    assert attrs.ip_address is None


def test_attributes_round_trip_into_the_database(db):
    host_id = db.upsert_host("local")
    db.update_host_attributes(host_id, **collect().as_dict())
    host = db.get_host(host_id)
    assert host["os_family"]
    assert host["last_seen_at"]


def test_as_dict_only_carries_attributes(db):
    """as_dict feeds update_host_attributes directly, so it must not carry
    anything that method would reject."""
    assert set(HostAttributes().as_dict()) == {
        "hostname", "ip_address", "os_family", "os_version", "kernel"}


# ── migration ──────────────────────────────────────────────────────────

def test_a_pre_v2_database_gains_identity_on_open(tmp_path):
    """Existing installs must migrate in place, keeping their host rows."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE hosts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00.000Z',
            updated_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00.000Z'
        );
        INSERT INTO hosts (label) VALUES ('legacy01'), ('legacy02');
    """)
    conn.commit()
    conn.close()

    with Database(path) as db:
        hosts = db.list_hosts()
        assert len(hosts) == 2, "migration must not drop existing hosts"
        uuids = {h["uuid"] for h in hosts}
        assert all(uuids) and len(uuids) == 2, "each gets its own identity"
        assert db.get_host_id("legacy01") is not None


def test_migration_is_idempotent(tmp_path):
    path = tmp_path / "t.db"
    with Database(path) as db:
        identity = db.get_host(db.upsert_host("web01"))["uuid"]
    with Database(path) as db:
        assert db.get_host_by_uuid(identity)["label"] == "web01", \
            "reopening must not re-mint identities"
