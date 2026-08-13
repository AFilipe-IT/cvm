"""
config_assessment/fetch/ssg_source.py
-------------------------------------
SCAP Security Guide (ComplianceAsCode/content) as a benchmark source.

WHY THIS EXISTS
---------------
`benchmark_fetcher.py` was written against stigviewer.com, which was the only
per-service source found in the 2026-07-01 investigation. As of 2026-08-13
stigviewer returns **HTTP 401 for every slug** — verified against
canonical_ubuntu_2204_lts, f5_nginx and kubernetes — so all 45 catalog entries
are unreachable. This module supplies a replacement for the OS-level targets.

ComplianceAsCode publishes the SCAP Security Guide as a public GitHub release
with no authentication. Two artefacts matter:

  controls/cis_<product>.yml      the CIS benchmark, structured: section id,
                                  title, level (l1_server/…), automated/manual
  linux_os/guide/**/rule.yml      per-rule substance: rationale, severity,
                                  CCE identifiers, and the expected value

WHAT MAKES THIS BETTER THAN stigviewer
--------------------------------------
The `template:` block of a rule.yml carries the (identifier, expected value)
pair *structurally*, with per-product overrides:

    template:
        name: file_permissions
        vars:
            filepath: /etc/shadow
            filemode: '0000'
            filemode@ubuntu2204: '0640'

Of the 400 rules referenced by the CIS Ubuntu 22.04 L1 Server profile, 290 carry
such a template. For those the directive and its secure value are recovered
DETERMINISTICALLY — no LLM, no inference. The remaining 110 fall back to the
normal LLM extraction path via <fixtext>/<check-content>, exactly like a STIG.

That distinction matters for the dissertation: a rule whose values came from the
template is machine-derived from the benchmark; a rule whose values came from
the LLM is not. `TemplateRule.deterministic` records which is which.

DIMENSIONS
----------
Templates also classify a rule by what it observes, which is what the v2's
multidimensional scoring needs:

  configuration   sysctl, sshd_lineinfile, accounts_password, kernel_module_*
  permissions     file_permissions, file_owner, file_groupowner, mount_option
  exposure        service_disabled, service_enabled, package_removed

The Jinja macros in rule.yml ({{{ ... }}}) are NOT rendered here. Only the
`template:` block, which is plain YAML, and the prose fields are read. Rendering
SSG templates properly needs their build system; this module deliberately does
less and says so.
"""

from __future__ import annotations

import re
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import yaml

# Release pinned by default so a scan is reproducible: an unpinned "latest"
# would silently change the knowledge base between runs, which is exactly what
# the reproducibility manifest exists to prevent.
SSG_REPO = "ComplianceAsCode/content"
SSG_DEFAULT_VERSION = "0.1.81"
SSG_ASSET = "scap-security-guide-{version}.tar.bz2"
SSG_DOWNLOAD = (
    "https://github.com/{repo}/releases/download/v{version}/{asset}")

# template name → dimension. Templates absent from this map fall to
# "configuration", the v1 default, so an unknown template never silently
# disappears from the assessment.
TEMPLATE_DIMENSIONS: dict[str, str] = {
    # permissions — filesystem metadata and privilege policy
    "file_permissions": "permissions",
    "file_owner": "permissions",
    "file_groupowner": "permissions",
    "mount_option": "permissions",
    "file_existence": "permissions",
    "sudo_defaults_option": "permissions",
    # exposure — what is installed, running, or listening
    "service_disabled": "exposure",
    "service_enabled": "exposure",
    "service_disabled_guard_var": "exposure",
    "service_enabled_guard_var": "exposure",
    "socket_disabled": "exposure",
    "package_removed": "exposure",
    "package_removed_guard_var": "exposure",
    # configuration — directives in files
    "package_installed": "configuration",
    "package_installed_guard_var": "configuration",
    "sysctl": "configuration",
    "sshd_lineinfile": "configuration",
    "lineinfile": "configuration",
    "accounts_password": "configuration",
    "kernel_module_disabled": "configuration",
    "cis_banner": "configuration",
    "mount": "configuration",
    "pam_options": "configuration",
    "pam_account_password_faillock": "configuration",
}

# For each template, which var holds the identifier and which the secure value.
# `None` for the value means it is not in vars and must be recovered elsewhere
# (sysctl keeps it in the description macro) or left to the LLM.
_TEMPLATE_FIELDS: dict[str, tuple[str, str | None]] = {
    "file_permissions": ("filepath", "filemode"),
    "file_owner": ("filepath", "uid_or_name"),
    "file_groupowner": ("filepath", "gid_or_name"),
    "mount_option": ("mountpoint", "mountoption"),
    "service_disabled": ("servicename", None),
    "service_enabled": ("servicename", None),
    "package_removed": ("pkgname", None),
    "package_installed": ("pkgname", None),
    "sshd_lineinfile": ("parameter", "value"),
    "sysctl": ("sysctlvar", None),
    "kernel_module_disabled": ("kernmodule", None),
}

_SYSCTL_VALUE = re.compile(
    r'describe_sysctl_option_value\(\s*sysctl="([^"]+)",\s*value="([^"]+)"\s*\)')
_TEMPLATE_BLOCK = re.compile(r"^template:\s*$", re.M)


class SSGError(RuntimeError):
    """The SSG archive could not be read, or lacks the requested product."""


@dataclass
class TemplateRule:
    """One CIS control resolved against its SSG rule definition.

    Attributes
    ----------
    deterministic:
        True when `identifier` and `good_value` came from the template block.
        False means the LLM must recover them from fixtext/check_content — the
        same path a STIG takes.
    """

    control_id: str          # CIS section, e.g. "1.1.1.1"
    control_title: str
    rule_name: str           # SSG rule directory name
    dimension: str
    identifier: str = ""
    good_value: str = ""
    bad_value: str = ""
    template: str = ""
    severity: str = "medium"
    rationale: str = ""
    description: str = ""
    cce: str = ""
    deterministic: bool = False
    references: dict[str, str] = field(default_factory=dict)

    @property
    def fixtext(self) -> str:
        """Text the XCCDF branch reads. Prefers the resolved pair when known."""
        if self.deterministic and self.good_value:
            return (f"Set {self.identifier} to {self.good_value}. "
                    f"{self.description}").strip()
        return self.description or self.control_title


class SSGArchive:
    """Read a SCAP Security Guide release tarball.

    The archive is opened lazily and read member-by-member; the 0.1.81 bz2 is
    8.6 MB compressed but expands well beyond that, so nothing is extracted to
    disk.
    """

    def __init__(self, archive_path: str | Path) -> None:
        self.path = Path(archive_path)
        if not self.path.exists():
            raise SSGError(f"SSG archive not found: {self.path}")
        self._rules: dict[str, dict] | None = None
        self._root = ""

    # ── public API ────────────────────────────────────────────────────
    def controls(self, product: str, level: str = "l1_server",
                 automated_only: bool = True) -> list[dict]:
        """Return the CIS controls for `product` at `level`.

        `product` is an SSG product id such as "ubuntu2204".
        """
        member = self._find(f"controls/cis_{product}.yml")
        if member is None:
            raise SSGError(
                f"no CIS control file for product '{product}' in {self.path.name}")
        doc = yaml.safe_load(self._read(member))
        out = []
        for c in doc.get("controls", []):
            if level and level not in (c.get("levels") or []):
                continue
            if automated_only and c.get("status") != "automated":
                continue
            out.append(c)
        return out

    def resolve(self, product: str, level: str = "l1_server",
                automated_only: bool = True) -> list[TemplateRule]:
        """Resolve every control at `level` against its rule definitions.

        A control may name several rules; each becomes its own TemplateRule,
        because each observes a different fact and therefore scores separately.
        Controls whose rules are absent from the archive are skipped — SSG
        references rules that live outside linux_os/guide (application-level
        content) and those carry no template to read.
        """
        rules = self._rule_index()
        out: list[TemplateRule] = []
        for ctrl in self.controls(product, level, automated_only):
            for raw_name in (ctrl.get("rules") or []):
                # Entries may be "rule_name=var_value"; the selector is not a
                # rule name and must be stripped before lookup.
                name = raw_name.split("=")[0].strip()
                body = rules.get(name)
                if body is None:
                    continue
                out.append(self._build(ctrl, name, body, product))
        return out

    # ── internals ─────────────────────────────────────────────────────
    def _build(self, ctrl: dict, name: str, body: str,
               product: str) -> TemplateRule:
        doc = _safe_yaml_fields(body)
        tmpl = _parse_template(body)
        tname = (tmpl or {}).get("name", "")
        tvars = _resolve_vars((tmpl or {}).get("vars", {}), product)

        rule = TemplateRule(
            control_id=str(ctrl.get("id", "")),
            control_title=str(ctrl.get("title", "")),
            rule_name=name,
            dimension=TEMPLATE_DIMENSIONS.get(tname, "configuration"),
            template=tname,
            severity=str(doc.get("severity") or "medium").lower(),
            rationale=_clean_prose(doc.get("rationale") or ""),
            description=_clean_prose(doc.get("description") or ""),
            cce=_cce_for(doc.get("identifiers") or {}, product),
            references={k: str(v) for k, v in (doc.get("references") or {}).items()
                        if k.startswith("cis") or k == "nist"},
        )

        ident_key, value_key = _TEMPLATE_FIELDS.get(tname, ("", None))
        if ident_key and ident_key in tvars:
            rule.identifier = str(tvars[ident_key])
            if value_key and value_key in tvars:
                rule.good_value = str(tvars[value_key])
                rule.deterministic = True
            elif tname == "sysctl":
                # sysctl keeps the value in the description macro, not in vars.
                m = _SYSCTL_VALUE.search(body)
                if m:
                    rule.identifier = m.group(1)
                    rule.good_value = m.group(2)
                    rule.deterministic = True
            elif tname in ("service_disabled", "package_removed"):
                # Presence IS the finding: the secure state is absence.
                rule.good_value = "absent"
                rule.bad_value = "present"
                rule.deterministic = True
            elif tname in ("service_enabled", "package_installed"):
                rule.good_value = "present"
                rule.bad_value = "absent"
                rule.deterministic = True
        return rule

    def _rule_index(self) -> dict[str, str]:
        """Map rule directory name → rule.yml text, read once per archive."""
        if self._rules is not None:
            return self._rules
        index: dict[str, str] = {}
        with tarfile.open(self.path, "r:*") as tf:
            for m in tf:
                if not m.isfile() or not m.name.endswith("/rule.yml"):
                    continue
                if "/linux_os/guide/" not in m.name:
                    continue
                name = m.name.rsplit("/", 2)[-2]
                fh = tf.extractfile(m)
                if fh is None:
                    continue
                index[name] = fh.read().decode("utf-8", "replace")
        self._rules = index
        return index

    def _find(self, suffix: str) -> str | None:
        with tarfile.open(self.path, "r:*") as tf:
            for m in tf:
                if m.isfile() and m.name.endswith(suffix):
                    return m.name
        return None

    def _read(self, member: str) -> str:
        with tarfile.open(self.path, "r:*") as tf:
            fh = tf.extractfile(member)
            if fh is None:
                raise SSGError(f"cannot read {member}")
            return fh.read().decode("utf-8", "replace")


# ── module-level helpers ──────────────────────────────────────────────

def _parse_template(body: str) -> dict | None:
    """Extract the `template:` block, which is plain YAML amid Jinja macros.

    yaml.safe_load on the whole file fails: rule.yml mixes YAML with Jinja
    ({{{ ... }}}) and templated keys. Slicing from `template:` to the next
    top-level key keeps the parse on ground that is genuinely YAML.
    """
    m = _TEMPLATE_BLOCK.search(body)
    if not m:
        return None
    lines = body[m.start():].splitlines()
    block = [lines[0]]
    for line in lines[1:]:
        if line and not line[0].isspace():
            break
        block.append(line)
    try:
        return (yaml.safe_load("\n".join(block)) or {}).get("template")
    except yaml.YAMLError:
        return None


def _safe_yaml_fields(body: str) -> dict:
    """Read the scalar/prose fields, skipping anything Jinja touched.

    Fields are parsed one at a time so a single templated value cannot make the
    whole rule unreadable.
    """
    out: dict = {}
    for key in ("severity", "rationale", "description", "identifiers",
                "references", "title"):
        m = re.search(rf"^{key}:\s*(.*(?:\n(?:[ \t].*|\s*)?)*)", body, re.M)
        if not m:
            continue
        chunk = m.group(0)
        # A value that is purely a Jinja macro carries no readable text.
        try:
            val = yaml.safe_load(chunk)
        except yaml.YAMLError:
            continue
        if isinstance(val, dict) and key in val:
            out[key] = val[key]
    return out


def _resolve_vars(tvars: dict | None, product: str) -> dict:
    """Collapse `key@product` overrides onto `key` for the target product.

    SSG writes the generic value under `key` and per-product exceptions under
    `key@ubuntu2204`. The override wins; unrelated products are dropped.

    A template may declare no vars at all (`vars:` with an empty body parses as
    None), so the empty case is normal, not an error.
    """
    if not tvars:
        return {}
    base = {k: v for k, v in tvars.items() if "@" not in k}
    for k, v in tvars.items():
        if "@" in k:
            stem, _, prod = k.partition("@")
            if prod == product:
                base[stem] = v
    return base


def _cce_for(identifiers: dict, product: str) -> str:
    """Return the CCE for this product, else any CCE present.

    A CCE from a sibling product still identifies the same control and is worth
    keeping for traceability, but only the product-specific one is ground truth
    for score comparison.
    """
    exact = identifiers.get(f"cce@{product}")
    if exact:
        return str(exact)
    for k, v in identifiers.items():
        if k.startswith("cce@"):
            return str(v)
    return ""


def _clean_prose(text: str) -> str:
    """Strip Jinja macros and HTML from SSG prose so the LLM reads plain text."""
    text = re.sub(r"\{\{\{.*?\}\}\}", "", text, flags=re.S)
    text = re.sub(r"<br\s*/?>", " ", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def ssg_download_url(version: str = SSG_DEFAULT_VERSION) -> str:
    """URL of the pinned SSG release tarball."""
    return SSG_DOWNLOAD.format(
        repo=SSG_REPO, version=version,
        asset=SSG_ASSET.format(version=version))


def iter_dimensions(rules: list[TemplateRule]) -> Iterator[tuple[str, int]]:
    """Yield (dimension, count) so callers can report coverage per dimension."""
    counts: dict[str, int] = {}
    for r in rules:
        counts[r.dimension] = counts.get(r.dimension, 0) + 1
    yield from sorted(counts.items(), key=lambda kv: -kv[1])
