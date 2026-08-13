"""
tests/test_collectors.py
------------------------
Tests for the permissions and exposure collectors.

The property defended throughout is the one the dimension model rests on: a
collector that could not look raises `CollectorUnavailable`, and never returns
an empty list. An empty list asserts "I looked and found nothing" — a claim
about a clean system — and manufacturing it from a failed observation is the
exact bug `not_assessed` exists to prevent.
"""

from __future__ import annotations

import os
import stat as stat_module

import pytest

from config_assessment.core.collectors import CollectorUnavailable, exposure, permissions


# ── permissions ────────────────────────────────────────────────────────

@pytest.fixture
def fake_root(tmp_path):
    """A filesystem root with the audited files present."""
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "passwd").write_text("root:x:0:0::/root:/bin/bash\n")
    (etc / "shadow").write_text("root:!:19000:0:99999:7:::\n")
    (etc / "passwd").chmod(0o644)
    (etc / "shadow").chmod(0o640)
    return tmp_path


class TestPermissionsCollector:
    def test_it_reports_mode_and_owner_for_each_path(self, fake_root):
        names = {d.name for d in permissions.collect(root=fake_root)}
        assert "file_mode:/etc/shadow" in names
        assert "file_owner:/etc/shadow" in names

    def test_modes_are_four_digit_octal(self, fake_root):
        """The knowledge base joins on strings, so '0644' and '644' are not
        the same key. Four digits is what the benchmark and `stat -c %a` use."""
        by_name = {d.name: d.value for d in permissions.collect(root=fake_root)}
        assert by_name["file_mode:/etc/passwd"] == "0644"
        assert by_name["file_mode:/etc/shadow"] == "0640"

    def test_a_loose_mode_is_reported_verbatim(self, fake_root):
        """The collector observes; judging 0644 against the benchmark is the
        knowledge base's job, not the collector's."""
        (fake_root / "etc/shadow").chmod(0o644)
        by_name = {d.name: d.value for d in permissions.collect(root=fake_root)}
        assert by_name["file_mode:/etc/shadow"] == "0644"

    def test_the_directive_name_is_stable_across_observed_values(self, fake_root):
        """The name is the join key, so it must not encode the value — one
        rule per path, not one rule per possible mode."""
        before = {d.name for d in permissions.collect(root=fake_root)}
        (fake_root / "etc/shadow").chmod(0o600)
        after = {d.name for d in permissions.collect(root=fake_root)}
        assert before == after

    def test_evidence_carries_the_file_metadata_shape(self, fake_root):
        """Contract §3: file_metadata evidence needs mode, owner and group,
        none of which fit source_file/line_number."""
        d = next(d for d in permissions.collect(root=fake_root)
                 if d.name == "file_mode:/etc/shadow")
        assert d.evidence["kind"] == "file_metadata"
        assert d.evidence["location"] == "/etc/shadow"
        assert d.evidence["mode"] == "0640"
        assert d.evidence["owner"]
        assert d.evidence["group"]

    def test_a_missing_file_yields_no_directive(self, tmp_path):
        """Absence is not an observation. Emitting a directive for a file that
        is not there would assert a reading nobody took."""
        (tmp_path / "etc").mkdir()
        (tmp_path / "etc/passwd").write_text("x")
        names = {d.name for d in permissions.collect(root=tmp_path)}
        assert "file_mode:/etc/passwd" in names
        assert "file_mode:/etc/shadow" not in names

    def test_paths_are_reported_as_absolute_not_root_relative(self, fake_root):
        """The rule is written against /etc/shadow. Reporting the scanner's
        temporary mount point would never match it."""
        d = next(d for d in permissions.collect(root=fake_root)
                 if d.name.startswith("file_mode:"))
        assert d.name.startswith("file_mode:/etc/")
        assert str(fake_root) not in d.name

    def test_an_unreadable_root_is_unavailable_not_empty(self, tmp_path):
        assert not (tmp_path / "nope").exists()
        with pytest.raises(CollectorUnavailable):
            permissions.collect(root=tmp_path / "nope")

    def test_a_root_with_no_audited_paths_is_empty_not_unavailable(self, tmp_path):
        """Looked, found none of them present — a real observation, and
        distinct from being unable to look at all."""
        assert permissions.collect(root=tmp_path) == []

    def test_an_orphaned_uid_is_reported_numerically(self, fake_root, monkeypatch):
        """A file owned by a deleted user is itself worth seeing; dropping it
        would hide exactly that."""
        monkeypatch.setattr(permissions.pwd, "getpwuid",
                            lambda _: (_ for _ in ()).throw(KeyError))
        d = next(d for d in permissions.collect(root=fake_root)
                 if d.name == "file_owner:/etc/shadow")
        assert d.value.split(":")[0].isdigit()


class TestSuidCollector:
    def test_it_finds_suid_binaries(self, tmp_path):
        binaries = tmp_path / "usr/bin"
        binaries.mkdir(parents=True)
        suid = binaries / "escalate"
        suid.write_text("#!/bin/sh\n")
        suid.chmod(0o4755)
        plain = binaries / "ordinary"
        plain.write_text("#!/bin/sh\n")
        plain.chmod(0o755)

        found = permissions.collect_suid(root=tmp_path, search_paths=("/usr/bin",))
        names = {d.name: d.value for d in found}
        assert "suid_binary:/usr/bin/escalate" in names
        assert names["suid_binary:/usr/bin/escalate"] == "suid"
        assert "suid_binary:/usr/bin/ordinary" not in names

    def test_sgid_and_combined_bits_are_distinguished(self, tmp_path):
        binaries = tmp_path / "usr/bin"
        binaries.mkdir(parents=True)
        for name, mode in (("sg", 0o2755), ("both", 0o6755)):
            f = binaries / name
            f.write_text("#!/bin/sh\n")
            f.chmod(mode)
        names = {d.name: d.value for d in
                 permissions.collect_suid(root=tmp_path, search_paths=("/usr/bin",))}
        assert names["suid_binary:/usr/bin/sg"] == "sgid"
        assert names["suid_binary:/usr/bin/both"] == "suid+sgid"

    def test_a_missing_directory_is_skipped(self, tmp_path):
        assert permissions.collect_suid(root=tmp_path,
                                        search_paths=("/nonexistent",)) == []


# ── exposure ───────────────────────────────────────────────────────────

def _proc_with(tmp_path, lines: list[str], name: str = "net/tcp") -> str:
    net = tmp_path / "net"
    net.mkdir(exist_ok=True)
    header = ("  sl  local_address rem_address   st tx_queue rx_queue tr "
              "tm->when retrnsmt   uid  timeout inode\n")
    (tmp_path / name).write_text(header + "".join(lines))
    return str(tmp_path)


def _row(local_hex: str, state: str = "0A", inode: str = "12345") -> str:
    return (f"   0: {local_hex} 00000000:0000 {state} 00000000:00000000 "
            f"00:00000000 00000000     0        0 {inode} 1 0000 100 0 0 10 0\n")


class TestExposureCollector:
    def test_a_wildcard_bind_is_world_facing(self, tmp_path):
        # 00000000:1F90 → 0.0.0.0:8080
        proc = _proc_with(tmp_path, [_row("00000000:1F90")])
        d = exposure.collect(proc_root=proc, resolve_process=False)[0]
        assert d.name == "listen:tcp/0.0.0.0:8080"
        assert d.evidence["world_facing"] is True

    def test_a_loopback_bind_is_not_world_facing(self, tmp_path):
        """The port is the same and the risk is not — this is the whole reason
        the dimension exists, and no config file states it."""
        # 0100007F:1F90 → 127.0.0.1:8080 (little-endian words)
        proc = _proc_with(tmp_path, [_row("0100007F:1F90")])
        d = exposure.collect(proc_root=proc, resolve_process=False)[0]
        assert d.name == "listen:tcp/127.0.0.1:8080"
        assert d.evidence["world_facing"] is False

    def test_a_concrete_lan_address_counts_as_exposed(self, tmp_path):
        """Narrower than a wildcard, but still reachable off-host."""
        # 0F02000A:0016 → 10.0.2.15:22 (the QEMU guest address)
        proc = _proc_with(tmp_path, [_row("0F02000A:0016")])
        d = exposure.collect(proc_root=proc, resolve_process=False)[0]
        assert d.name == "listen:tcp/10.0.2.15:22"
        assert d.evidence["world_facing"] is True

    def test_an_ipv4_mapped_loopback_is_not_world_facing(self, tmp_path):
        """`ipaddress` reports is_loopback False for ::ffff:127.0.0.1 — the v6
        address is not in ::1/128 — but a service bound there is bound to
        127.0.0.1 and is unreachable off-host. Reporting it as exposed is a
        false positive, the direction that costs the dimension its credibility.
        """
        net = tmp_path / "net"
        net.mkdir()
        (tmp_path / "net/tcp").write_text("header\n")
        (tmp_path / "net/tcp6").write_text(
            "header\n" + _row("0000000000000000FFFF00000100007F:0050"))
        d = exposure.collect(proc_root=str(tmp_path), resolve_process=False)[0]
        assert d.evidence["world_facing"] is False

    def test_the_ipv6_wildcard_is_world_facing(self, tmp_path):
        """The v6 unwrapping must not accidentally spare `::`."""
        net = tmp_path / "net"
        net.mkdir()
        (tmp_path / "net/tcp").write_text("header\n")
        (tmp_path / "net/tcp6").write_text(
            "header\n" + _row("00000000000000000000000000000000:0050"))
        d = exposure.collect(proc_root=str(tmp_path), resolve_process=False)[0]
        assert d.evidence["world_facing"] is True

    def test_the_ipv6_loopback_is_not_world_facing(self, tmp_path):
        net = tmp_path / "net"
        net.mkdir()
        (tmp_path / "net/tcp").write_text("header\n")
        (tmp_path / "net/tcp6").write_text(
            "header\n" + _row("00000000000000000000000001000000:0050"))
        d = exposure.collect(proc_root=str(tmp_path), resolve_process=False)[0]
        assert d.name == "listen:tcp6/::1:80"
        assert d.evidence["world_facing"] is False

    def test_only_listening_sockets_are_reported(self, tmp_path):
        """Established connections are transient and say nothing about the
        host's attack surface."""
        proc = _proc_with(tmp_path, [
            _row("00000000:1F90", state="0A"),
            _row("00000000:0050", state="01"),  # ESTABLISHED
        ])
        found = exposure.collect(proc_root=proc, resolve_process=False)
        assert len(found) == 1
        assert "8080" in found[0].name

    def test_evidence_carries_the_socket_shape(self, tmp_path):
        proc = _proc_with(tmp_path, [_row("00000000:1F90")])
        ev = exposure.collect(proc_root=proc, resolve_process=False)[0].evidence
        assert ev["kind"] == "listening_socket"
        assert ev["location"] == "tcp/0.0.0.0:8080"
        assert "process" in ev and "pid" in ev

    def test_an_unresolvable_process_is_unknown_not_guessed(self, tmp_path):
        proc = _proc_with(tmp_path, [_row("00000000:1F90")])
        d = exposure.collect(proc_root=proc, resolve_process=False)[0]
        assert d.value == "unknown"
        assert d.evidence["process"] is None

    def test_the_directive_name_carries_the_binding(self, tmp_path):
        """A rule is about 'something listening on 0.0.0.0:8080', so the
        address must be the join key, not the value."""
        proc = _proc_with(tmp_path, [_row("00000000:1F90")])
        d = exposure.collect(proc_root=proc, resolve_process=False)[0]
        assert "0.0.0.0:8080" in d.name

    def test_ipv6_sockets_are_parsed(self, tmp_path):
        net = tmp_path / "net"
        net.mkdir()
        (tmp_path / "net/tcp").write_text("header\n")
        (tmp_path / "net/tcp6").write_text(
            "header\n" + _row("00000000000000000000000000000000:0050"))
        found = exposure.collect(proc_root=str(tmp_path), resolve_process=False)
        assert any(d.name.startswith("listen:tcp6/") for d in found)

    def test_duplicate_bindings_are_reported_once(self, tmp_path):
        proc = _proc_with(tmp_path, [_row("00000000:1F90", inode="1"),
                                     _row("00000000:1F90", inode="2")])
        assert len(exposure.collect(proc_root=proc, resolve_process=False)) == 1

    def test_a_malformed_row_does_not_cost_the_valid_ones(self, tmp_path):
        proc = _proc_with(tmp_path, ["garbage line\n", _row("00000000:1F90")])
        found = exposure.collect(proc_root=proc, resolve_process=False)
        assert len(found) == 1

    def test_no_socket_table_is_unavailable_not_empty(self, tmp_path):
        """A mounted disk image has no live sockets. Reporting [] would assert
        the system listens on nothing — a claim about a system that is not
        running."""
        with pytest.raises(CollectorUnavailable):
            exposure.collect(proc_root=str(tmp_path / "absent"))

    def test_an_empty_socket_table_is_a_real_empty_result(self, tmp_path):
        """Present and readable, with no listeners: genuinely nothing exposed."""
        proc = _proc_with(tmp_path, [])
        assert exposure.collect(proc_root=proc, resolve_process=False) == []


class TestServiceClassification:
    """The port-independent directive: the collector answers the QUESTION
    ("is redis exposed?") so a single rule covers the service wherever it
    listens. This is what closes the gap the port-named rules leave open."""

    @staticmethod
    def _with_process(tmp_path, hex_addr, comm, inode="4242"):
        net = tmp_path / "net"
        net.mkdir(exist_ok=True)
        (tmp_path / "net/tcp").write_text("header\n" + _row(hex_addr, inode=inode))
        (tmp_path / "net/tcp6").write_text("header\n")
        pid = tmp_path / "812"
        (pid / "fd").mkdir(parents=True)
        (pid / "comm").write_text(f"{comm}\n")
        os.symlink(f"socket:[{inode}]", pid / "fd/3")
        return str(tmp_path)

    def test_a_conventional_port_identifies_the_service(self, tmp_path):
        # 18EB = 6379
        proc = _proc_with(tmp_path, [_row("00000000:18EB")])
        found = {d.name: d for d in exposure.collect(proc_root=proc,
                                                     resolve_process=False)}
        assert found["exposed_service:redis"].value == "world_facing"
        assert found["exposed_service:redis"].evidence["identified_by"] == "port"

    def test_a_non_standard_port_is_caught_via_the_process(self, tmp_path):
        """The gap the port-named rules leave open: 'security by non-standard
        port' is exactly the assumption an audit must not share."""
        # 1E61 = 7777, no conventional service
        proc = self._with_process(tmp_path, "00000000:1E61", "redis-server")
        found = {d.name: d for d in exposure.collect(proc_root=proc)}
        assert found["exposed_service:redis"].value == "world_facing"
        assert found["exposed_service:redis"].evidence["identified_by"] == "process"

    def test_the_process_name_beats_the_port_convention(self, tmp_path):
        """Something else on 6379 is not redis, whatever the port suggests."""
        proc = self._with_process(tmp_path, "00000000:18EB", "mongod")
        found = {d.name for d in exposure.collect(proc_root=proc)}
        assert "exposed_service:mongodb" in found
        assert "exposed_service:redis" not in found

    def test_a_loopback_service_is_classified_not_omitted(self, tmp_path):
        """`loopback` is a real answer to the exposure question, and matches no
        rule — the finding is the exposure, not the presence of the service."""
        proc = _proc_with(tmp_path, [_row("0100007F:18EB")])
        found = {d.name: d.value for d in exposure.collect(proc_root=proc,
                                                           resolve_process=False)}
        assert found["exposed_service:redis"] == "loopback"

    def test_an_unidentifiable_service_is_not_guessed(self, tmp_path):
        """A non-standard port with an unresolvable process yields NO service
        directive. A wrong attribution would put a confident, citable finding
        against a service that is not there — worse than an acknowledged gap."""
        proc = _proc_with(tmp_path, [_row("00000000:1E61")])
        found = {d.name for d in exposure.collect(proc_root=proc,
                                                  resolve_process=False)}
        assert not any(n.startswith("exposed_service:") for n in found)
        assert "listen:tcp/0.0.0.0:7777" in found, "the socket is still observed"

    def test_a_generic_process_name_falls_back_to_the_port(self, tmp_path):
        """`java` identifies nothing; the port is the weaker but honest signal."""
        proc = self._with_process(tmp_path, "00000000:23F0", "java")  # 9200
        found = {d.name: d for d in exposure.collect(proc_root=proc)}
        assert found["exposed_service:elasticsearch"].evidence[
            "identified_by"] == "port"

    def test_a_dual_stack_service_is_reported_once(self, tmp_path):
        """Two sockets, one service: the console must not show the finding
        twice."""
        net = tmp_path / "net"
        net.mkdir()
        (tmp_path / "net/tcp").write_text("header\n" + _row("00000000:18EB"))
        (tmp_path / "net/tcp6").write_text(
            "header\n" + _row("00000000000000000000000000000000:18EB", inode="2"))
        found = [d for d in exposure.collect(proc_root=str(tmp_path),
                                             resolve_process=False)
                 if d.name == "exposed_service:redis"]
        assert len(found) == 1
        assert found[0].value == "world_facing"

    def test_a_world_facing_binding_decides_a_mixed_service(self, tmp_path):
        """Listening on loopback as well does not make a reachable service
        unreachable — the reverse would let an extra socket mask the finding."""
        net = tmp_path / "net"
        net.mkdir()
        (tmp_path / "net/tcp").write_text("header\n" + _row("0100007F:18EB"))
        (tmp_path / "net/tcp6").write_text(
            "header\n" + _row("00000000000000000000000000000000:18EB", inode="2"))
        found = [d for d in exposure.collect(proc_root=str(tmp_path),
                                             resolve_process=False)
                 if d.name == "exposed_service:redis"]
        assert len(found) == 1
        assert found[0].value == "world_facing"

    def test_the_socket_directives_survive_alongside(self, tmp_path):
        """Both are emitted: they answer different questions."""
        proc = _proc_with(tmp_path, [_row("00000000:18EB")])
        names = {d.name for d in exposure.collect(proc_root=proc,
                                                  resolve_process=False)}
        assert "listen:tcp/0.0.0.0:6379" in names
        assert "exposed_service:redis" in names
