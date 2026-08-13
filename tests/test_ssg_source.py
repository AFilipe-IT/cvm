"""
tests/test_ssg_source.py
------------------------
Tests for the SCAP Security Guide source (config_assessment.fetch.ssg_source
and the "ssg" branch of BenchmarkFetcher).

The network is never touched: every test builds a small tarball with the same
shape as a real SSG release. The fixtures reproduce real rule.yml content
verbatim where the parsing is subtle — the Jinja macros, the `key@product`
overrides and the sysctl value living in the description rather than in vars are
all real cases taken from scap-security-guide 0.1.81, not invented ones.
"""

from __future__ import annotations

import io
import tarfile

import pytest

from config_assessment.fetch.benchmark_fetcher import (
    BenchmarkFetcher, FetchError, _ssg_rules_to_xccdf)
from config_assessment.build.benchmark_extractor import XCCDFExtractor
from config_assessment.fetch.ssg_source import (
    SSGArchive, SSGError, TemplateRule, _clean_prose, _resolve_vars,
    iter_dimensions, ssg_download_url)


# ── fixtures ───────────────────────────────────────────────────────────

ROOT = "scap-security-guide-0.1.81"

CONTROLS_YML = """\
policy: CIS Benchmark for Ubuntu 22.04 LTS
id: cis_ubuntu2204
version: 2.0.0
controls:
    - id: 1.1.1.1
      title: Ensure cramfs kernel module is not available (Automated)
      levels:
          - l1_server
      rules:
          - kernel_module_cramfs_disabled
      status: automated

    - id: 6.1.1
      title: Ensure permissions on /etc/shadow are configured (Automated)
      levels:
          - l1_server
      rules:
          - file_permissions_etc_shadow
      status: automated

    - id: 3.3.2
      title: Ensure ICMP redirects are not accepted (Automated)
      levels:
          - l1_server
      rules:
          - sysctl_net_ipv4_conf_all_accept_redirects
      status: automated

    - id: 2.1.2
      title: Ensure avahi daemon services are not in use (Automated)
      levels:
          - l1_server
      rules:
          - service_avahi-daemon_disabled
      status: automated

    - id: 9.9.9
      title: A manual control that must be skipped
      levels:
          - l1_server
      rules:
          - some_manual_rule
      status: manual

    - id: 8.8.8
      title: An l2-only control
      levels:
          - l2_server
      rules:
          - kernel_module_cramfs_disabled
      status: automated
"""

# Real shape: per-product override wins over the generic value.
RULE_SHADOW = """\
documentation_complete: true

title: 'Verify Permissions on shadow File'

description:  |-
    {{{ describe_file_permissions(file="/etc/shadow", perms="0640") }}}

rationale: |-
    The <tt>/etc/shadow</tt> file stores password hashes.
    <br />
    Protection of this file is critical for system security.

severity: medium

identifiers:
    cce@rhel8: CCE-80813-9
    cce@ubuntu2204: CCE-90000-1

references:
    cis@ubuntu2204: 6.1.1
    nist: CM-6(a),AC-6(1)

template:
    name: file_permissions
    vars:
        filepath: /etc/shadow
        filemode: '0000'
        filemode@ubuntu2204: '0640'
        filemode@sle15: '0640'
"""

# Real shape: the secure value is in the description macro, not in vars.
RULE_SYSCTL = """\
documentation_complete: true

title: 'Disable Accepting ICMP Redirects for All IPv4 Interfaces'

description: '{{{ describe_sysctl_option_value(sysctl="net.ipv4.conf.all.accept_redirects", value="0") }}}'

rationale: |-
    ICMP redirect messages are unauthenticated and modify the host's route
    table. An illicit redirect could result in a man-in-the-middle attack.

severity: medium

identifiers:
    cce@ubuntu2204: CCE-90001-2

template:
    name: sysctl
    vars:
        sysctlvar: net.ipv4.conf.all.accept_redirects
        datatype: int
"""

RULE_SERVICE = """\
documentation_complete: true

title: 'Disable Avahi Server Software'

rationale: |-
    Automatic discovery of network services is not required and increases the
    attack surface.

severity: medium

template:
    name: service_disabled
    vars:
        servicename: avahi-daemon
        packagename: avahi
        packagename@ubuntu2204: avahi-daemon
"""

RULE_NO_TEMPLATE = """\
documentation_complete: true

title: 'Disable Modprobe Loading of USB Storage Driver'

rationale: |-
    Restricting USB access reduces the exposure of the system.

severity: low
"""


def _make_archive(path, controls=CONTROLS_YML, rules=None):
    """Write a tarball with the directory layout of a real SSG release."""
    rules = rules if rules is not None else {
        "file_permissions_etc_shadow": RULE_SHADOW,
        "sysctl_net_ipv4_conf_all_accept_redirects": RULE_SYSCTL,
        "service_avahi-daemon_disabled": RULE_SERVICE,
        "kernel_module_cramfs_disabled": RULE_NO_TEMPLATE,
    }
    with tarfile.open(path, "w:bz2") as tf:
        def add(name, text):
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

        add(f"{ROOT}/controls/cis_ubuntu2204.yml", controls)
        for name, body in rules.items():
            add(f"{ROOT}/linux_os/guide/system/{name}/rule.yml", body)
    return str(path)


@pytest.fixture
def archive(tmp_path):
    return SSGArchive(_make_archive(tmp_path / "ssg.tar.bz2"))


# ── controls ───────────────────────────────────────────────────────────

def test_controls_filters_by_level_and_status(archive):
    ctrls = archive.controls("ubuntu2204")
    ids = {c["id"] for c in ctrls}
    assert ids == {"1.1.1.1", "6.1.1", "3.3.2", "2.1.2"}
    assert "9.9.9" not in ids, "manual controls must be excluded"
    assert "8.8.8" not in ids, "l2-only controls must be excluded at l1_server"


def test_controls_can_include_manual(archive):
    ctrls = archive.controls("ubuntu2204", automated_only=False)
    assert "9.9.9" in {c["id"] for c in ctrls}


def test_unknown_product_raises(archive):
    with pytest.raises(SSGError, match="no CIS control file"):
        archive.controls("rhel9")


def test_missing_archive_raises(tmp_path):
    with pytest.raises(SSGError, match="not found"):
        SSGArchive(tmp_path / "absent.tar.bz2")


# ── deterministic resolution ───────────────────────────────────────────

def test_file_permissions_uses_product_override(archive):
    rule = _by_control(archive, "6.1.1")
    assert rule.identifier == "/etc/shadow"
    # 0640 (ubuntu2204), NOT the generic 0000 — this is the whole point of the
    # per-product override.
    assert rule.good_value == "0640"
    assert rule.deterministic is True
    assert rule.dimension == "permissions"


def test_sysctl_value_recovered_from_description(archive):
    rule = _by_control(archive, "3.3.2")
    assert rule.identifier == "net.ipv4.conf.all.accept_redirects"
    assert rule.good_value == "0"
    assert rule.deterministic is True
    assert rule.dimension == "configuration"


def test_service_absence_is_the_secure_state(archive):
    rule = _by_control(archive, "2.1.2")
    assert rule.identifier == "avahi-daemon"
    assert (rule.good_value, rule.bad_value) == ("absent", "present")
    assert rule.dimension == "exposure"


def test_rule_without_template_is_not_deterministic(archive):
    rule = _by_control(archive, "1.1.1.1")
    assert rule.deterministic is False
    assert rule.identifier == ""
    # Still classified, so it never vanishes from the assessment.
    assert rule.dimension == "configuration"


def test_cce_prefers_the_product_specific_identifier(archive):
    assert _by_control(archive, "6.1.1").cce == "CCE-90000-1"


def test_rationale_is_stripped_of_html_and_jinja(archive):
    rule = _by_control(archive, "6.1.1")
    assert "<tt>" not in rule.rationale
    assert "<br" not in rule.rationale
    assert "password hashes" in rule.rationale


def test_resolve_skips_rules_absent_from_the_archive(tmp_path):
    """SSG references rules living outside linux_os/guide; those are skipped."""
    arch = SSGArchive(_make_archive(tmp_path / "a.tar.bz2", rules={}))
    assert arch.resolve("ubuntu2204") == []


def test_dimensions_are_reported(archive):
    dims = dict(iter_dimensions(archive.resolve("ubuntu2204")))
    assert dims == {"configuration": 2, "permissions": 1, "exposure": 1}


# ── helpers ────────────────────────────────────────────────────────────

def test_resolve_vars_applies_only_the_matching_product():
    out = _resolve_vars(
        {"filemode": "0000", "filemode@ubuntu2204": "0640",
         "filemode@sle15": "0600"}, "ubuntu2204")
    assert out == {"filemode": "0640"}


def test_resolve_vars_tolerates_empty_vars():
    assert _resolve_vars(None, "ubuntu2204") == {}
    assert _resolve_vars({}, "ubuntu2204") == {}


def test_clean_prose_removes_macros():
    assert _clean_prose("{{{ macro(x=1) }}} real text") == "real text"


def test_download_url_is_pinned_by_default():
    url = ssg_download_url()
    assert "0.1.81" in url and url.endswith(".tar.bz2")


def test_fixtext_states_the_pair_when_deterministic():
    r = TemplateRule(control_id="1.1", control_title="t", rule_name="r",
                     dimension="permissions", identifier="/etc/shadow",
                     good_value="0640", deterministic=True,
                     description="Protect the file.")
    assert "Set /etc/shadow to 0640" in r.fixtext


def test_fixtext_falls_back_to_prose_when_not_deterministic():
    r = TemplateRule(control_id="1.1", control_title="Control title",
                     rule_name="r", dimension="configuration")
    assert r.fixtext == "Control title"


# ── XCCDF emission ─────────────────────────────────────────────────────

def test_emitted_xccdf_is_readable_by_the_existing_extractor(archive, tmp_path):
    """The whole point of emitting XCCDF: plugin add consumes it unchanged."""
    rules = archive.resolve("ubuntu2204")
    xml = _ssg_rules_to_xccdf("ubuntu CIS", "0.1.81", rules)
    out = tmp_path / "ssg.xml"
    out.write_text(xml, encoding="utf-8")

    title, parsed = XCCDFExtractor().load(str(out))
    assert title == "ubuntu CIS"
    assert len(parsed) == len(rules)
    assert all(r["title"] for r in parsed)


def test_emitted_xccdf_carries_dimension_and_provenance(archive, tmp_path):
    import xml.etree.ElementTree as ET
    xml = _ssg_rules_to_xccdf("t", "", archive.resolve("ubuntu2204"))
    root = ET.fromstring(xml)
    ns = {"x": "http://checklists.nist.gov/xccdf/1.1"}
    cvm = "{https://github.com/AFilipe-IT/cvm}"
    found = {r.get("id"): (r.get(f"{cvm}dimension"), r.get(f"{cvm}deterministic"))
             for r in root.findall(".//x:Rule", ns)}
    assert found["file_permissions_etc_shadow"] == ("permissions", "true")
    assert found["kernel_module_cramfs_disabled"] == ("configuration", "false")


def test_emitted_xccdf_puts_the_cce_in_the_check(archive, tmp_path):
    xml = _ssg_rules_to_xccdf("t", "", archive.resolve("ubuntu2204"))
    assert "CCE-90000-1" in xml


# ── fetcher integration ────────────────────────────────────────────────

def test_fetch_ssg_uses_a_cached_archive_without_network(tmp_path):
    """A present archive must not be re-downloaded — no network in tests."""
    _make_archive(tmp_path / "scap-security-guide-0.1.81.tar.bz2")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        '{"ubuntu2204": {"service_name": "Ubuntu 22.04 LTS", "sources": ['
        '{"type": "ssg", "product": "ubuntu2204", "version": "0.1.81",'
        ' "level": "l1_server", "format": "xccdf", "title": "CIS Ubuntu"}]}}',
        encoding="utf-8")

    out = BenchmarkFetcher(catalog).fetch("ubuntu2204", dest_dir=tmp_path)
    assert out.endswith("SSG_ubuntu2204_l1_server.xml")
    _, rules = XCCDFExtractor().load(out)
    assert len(rules) == 4


def test_fetch_ssg_without_product_raises(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        '{"x": {"sources": [{"type": "ssg", "version": "0.1.81"}]}}',
        encoding="utf-8")
    with pytest.raises(FetchError, match="needs a 'product'"):
        BenchmarkFetcher(catalog).fetch("x", dest_dir=tmp_path)


def test_stigviewer_401_explains_the_source_is_closed(tmp_path):
    """A bare 'HTTP 401' would read as a bad service name. It is not."""
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        '{"nginx": {"sources": [{"type": "stigviewer", "slug": "f5_nginx"}]}}',
        encoding="utf-8")
    with pytest.raises(FetchError) as exc:
        with _http_raising("HTTP 401 for https://www.stigviewer.com/x"):
            BenchmarkFetcher(catalog).fetch("nginx", dest_dir=tmp_path)
    assert "requires authentication" in str(exc.value)
    assert "plugin add --source" in str(exc.value), "must state the way out"


def test_shipped_catalog_lists_ssg_first_for_ubuntu2204():
    """SSG must be tried before the dead stigviewer source."""
    entry = next(e for e in BenchmarkFetcher().list_available()
                 if e["service"] == "ubuntu2204")
    assert entry["sources"][0]["type"] == "ssg"


# ── test helpers ───────────────────────────────────────────────────────

def _by_control(archive, control_id):
    return next(r for r in archive.resolve("ubuntu2204")
                if r.control_id == control_id)


class _http_raising:
    """Patch _http_get to raise a FetchError with a given message."""

    def __init__(self, message):
        self.message = message

    def __enter__(self):
        from unittest.mock import patch
        self._p = patch(
            "config_assessment.fetch.benchmark_fetcher._http_get",
            side_effect=FetchError(self.message))
        self._p.start()
        return self

    def __exit__(self, *exc):
        self._p.stop()
        return False
