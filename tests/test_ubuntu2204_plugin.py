"""
tests/test_ubuntu2204_plugin.py
-------------------------------
Tests for the ubuntu2204 system-state target.

The claim under test is the thesis's central one for this phase: a system whose
CONFIG FILES are clean can still be misconfigured in ways only system state
reveals, and v1 cannot see them. So these tests assert the delta, not just that
the plugin runs — a scan finding /etc/shadow at 0644 through the unmodified
scoring pipeline is the evidence.
"""

from __future__ import annotations

import pytest

from config_assessment.core import runtime
from config_assessment.core.db.database import Database
from config_assessment.plugins.ubuntu2204 import Ubuntu2204Plugin
from config_assessment.plugins.ubuntu2204.build_ubuntu2204 import run_build
from config_assessment.plugins.ubuntu2204.rules import ENTRIES


@pytest.fixture(autouse=True)
def only_this_plugin():
    """Isolate the registry so detection is not decided by another plugin."""
    original = list(runtime._REGISTRY)
    runtime._REGISTRY.clear()
    runtime._REGISTRY.append(Ubuntu2204Plugin())
    yield
    runtime._REGISTRY.clear()
    runtime._REGISTRY.extend(original)


@pytest.fixture
def ubuntu_root(tmp_path):
    """An Ubuntu root with two flaws no config parser can see."""
    etc = tmp_path / "etc"
    (etc / "ssh").mkdir(parents=True)
    (etc / "os-release").write_text(
        'NAME="Ubuntu"\nVERSION="22.04.3 LTS"\nID=ubuntu\n')
    (etc / "passwd").write_text("root:x:0:0::/root:/bin/bash\n")
    (etc / "shadow").write_text("root:!:19000:0:99999:7:::\n")
    (etc / "ssh/sshd_config").write_text("Port 22\n")
    (etc / "passwd").chmod(0o644)          # correct
    (etc / "shadow").chmod(0o644)          # FLAW: should be 0640
    (etc / "ssh/sshd_config").chmod(0o644)  # FLAW: should be 0600
    return tmp_path


@pytest.fixture
def seeded_db(tmp_path):
    path = str(tmp_path / "rules.db")
    run_build(path)
    return path


class TestDetection:
    def test_an_ubuntu_root_is_detected(self, ubuntu_root):
        assert Ubuntu2204Plugin().detect(str(ubuntu_root)) is True

    def test_a_directory_merely_named_ubuntu_is_not(self, tmp_path):
        """Detection reads /etc/os-release rather than trusting the path name."""
        d = tmp_path / "ubuntu"
        d.mkdir()
        assert Ubuntu2204Plugin().detect(str(d)) is False

    def test_a_non_ubuntu_root_is_not_detected(self, tmp_path):
        etc = tmp_path / "etc"
        etc.mkdir()
        (etc / "os-release").write_text('NAME="Debian GNU/Linux"\nID=debian\n')
        assert Ubuntu2204Plugin().detect(str(tmp_path)) is False

    def test_a_config_file_is_not_detected(self, tmp_path):
        """The input mode is a filesystem ROOT; a lone config file belongs to
        another target, and claiming it would hijack v1's scans."""
        f = tmp_path / "sysctl.conf"
        f.write_text("net.ipv4.ip_forward = 0\n")
        assert Ubuntu2204Plugin().detect(str(f)) is False


class TestReachableFromTheCli:
    """The plugin detecting a root is not enough — `resolve` has to route to it.

    `resolve` used to send every directory straight to `resolve_directory`,
    which looks for a known config FILE (nginx.conf, sshd_config, ...) and
    raises when it finds none. An Ubuntu root contains no such entry point, so
    the target was unreachable from the CLI however well `detect` worked: it
    could only be driven through the Python API. These tests pin the routing,
    not the detection, because that is the half that was missing.
    """

    def test_an_ubuntu_root_resolves_to_the_plugin(self, ubuntu_root):
        from config_assessment.core.input_resolver import resolve

        resolved = resolve(str(ubuntu_root))
        assert resolved.mode == "directory"
        assert resolved.metadata["target"] == "ubuntu2204"

    def test_a_service_directory_still_uses_the_file_search(self, tmp_path):
        """The fallback is what every existing directory scan depends on, so a
        claiming plugin must not shadow it. No plugin claims this root, and the
        nginx.conf inside it must still be found the way it always was."""
        from config_assessment.core.input_resolver import resolve

        (tmp_path / "nginx.conf").write_text("server_tokens off;\n")
        resolved = resolve(str(tmp_path))
        assert resolved.mode == "directory"
        assert resolved.metadata["entry_file"] == "nginx.conf"

    def test_an_unclaimed_directory_with_no_config_still_raises(self, tmp_path):
        """The error is load-bearing: it tells the operator the path holds
        nothing assessable. Silently resolving it would report a clean scan of
        a directory that was never assessed."""
        from config_assessment.core.input_resolver import resolve

        with pytest.raises(FileNotFoundError):
            resolve(str(tmp_path))


class TestCollection:
    def test_it_produces_permissions_directives(self, ubuntu_root):
        names = {d.name for d in Ubuntu2204Plugin().parse_config(str(ubuntu_root))}
        assert "file_mode:/etc/shadow" in names
        assert "file_owner:/etc/shadow" in names

    def test_an_image_root_yields_no_socket_directives(self, ubuntu_root):
        """Sockets belong to a RUNNING system. The scanning host's own sockets
        are not the image's, and reporting them would be a fabrication."""
        directives = Ubuntu2204Plugin().parse_config(str(ubuntu_root))
        assert not [d for d in directives if d.name.startswith("listen:")]

    def test_an_unavailable_collector_does_not_abort_the_scan(self, ubuntu_root):
        """Exposure is unavailable against an image, and permissions must still
        be collected — one dimension going unassessed is not a scan failure."""
        assert Ubuntu2204Plugin().parse_config(str(ubuntu_root))


class TestScoringEndToEnd:
    def test_it_finds_the_loose_shadow_mode(self, ubuntu_root, seeded_db):
        with Database(seeded_db) as db:
            result = runtime.scan(str(ubuntu_root), db)
        found = {(i.directive, i.bad_value) for i in result.issues}
        assert ("file_mode:/etc/shadow", "0644") in found

    def test_it_finds_the_loose_sshd_config_mode(self, ubuntu_root, seeded_db):
        with Database(seeded_db) as db:
            result = runtime.scan(str(ubuntu_root), db)
        found = {(i.directive, i.bad_value) for i in result.issues}
        assert ("file_mode:/etc/ssh/sshd_config", "0644") in found

    def test_a_correct_passwd_mode_is_not_flagged(self, ubuntu_root, seeded_db):
        """0644 is CORRECT for /etc/passwd — name resolution needs it readable.
        A rule flagging it would fire on every properly configured Ubuntu host,
        which is the kind of false positive that trains operators to ignore the
        tool."""
        with Database(seeded_db) as db:
            result = runtime.scan(str(ubuntu_root), db)
        assert not [i for i in result.issues
                    if i.directive == "file_mode:/etc/passwd"]

    def test_the_findings_land_in_the_permissions_dimension(
            self, ubuntu_root, seeded_db):
        """The point of the phase: these must NOT be filed as `configuration`."""
        from config_assessment.core.engines.dimensions import group_by_dimension
        with Database(seeded_db) as db:
            result = runtime.scan(str(ubuntu_root), db)
        assert set(group_by_dimension(result.issues)) == {"permissions"}

    def test_a_clean_root_scores_zero_rather_than_failing(
            self, ubuntu_root, seeded_db):
        (ubuntu_root / "etc/shadow").chmod(0o640)
        (ubuntu_root / "etc/ssh/sshd_config").chmod(0o600)
        with Database(seeded_db) as db:
            result = runtime.scan(str(ubuntu_root), db)
        assert result.issues == []
        assert result.global_temporal_score == 0.0

    def test_the_scan_is_deterministic(self, ubuntu_root, seeded_db):
        """Same input, same manifest, same score — the determinism claim."""
        with Database(seeded_db) as db:
            first = runtime.scan(str(ubuntu_root), db)
            second = runtime.scan(str(ubuntu_root), db)
        assert first.global_temporal_score == second.global_temporal_score
        assert {i.directive for i in first.issues} == \
               {i.directive for i in second.issues}


class TestRules:
    def test_the_build_is_idempotent(self, tmp_path):
        path = str(tmp_path / "r.db")
        first = run_build(path)["misconfigs"]
        run_build(path)
        with Database(path) as db:
            assert len(db.get_all_misconfigurations("ubuntu2204")) == first

    def test_every_rule_carries_a_benchmark_section(self):
        """A finding with no citation cannot be defended to an auditor."""
        assert all(entry[3].strip() for entry in ENTRIES)

    def test_every_rule_carries_a_recommendation(self):
        assert all(entry[9].strip() for entry in ENTRIES)

    def test_permission_rules_expect_octal_modes(self):
        """The join is on exact strings, so a rule written '644' would never
        match a collector reporting '0644'."""
        for directive, bad, good, *_ in ENTRIES:
            if directive.startswith("file_mode:"):
                assert len(bad) == 4 and bad.startswith("0"), directive
                assert len(good) == 4 and good.startswith("0"), directive

    def test_no_rule_flags_a_readable_passwd_or_group(self):
        """0644 is the correct, required mode for these files."""
        for directive, bad, *_ in ENTRIES:
            if directive in ("file_mode:/etc/passwd", "file_mode:/etc/group"):
                assert bad != "0644", \
                    f"{directive} 0644 is correct, not a finding"
