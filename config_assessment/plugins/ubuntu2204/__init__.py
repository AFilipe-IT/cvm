"""
plugins/ubuntu2204/__init__.py
------------------------------
Ubuntu 22.04 whole-system target — the SYSTEM STATE controls of CIS Ubuntu
22.04 L1 Server: file permissions and network exposure.

WHY THIS IS A SEPARATE TARGET FROM `ubuntu`
    The `ubuntu` plugin's narrow, config-file-only scope is deliberate and
    documented: it is the fair basis for the OpenSCAP comparison in the
    evaluation, where both tools see the same controls. Widening it in place
    would silently change what that comparison measures, invalidating a
    result that has already been validated.

    So this is a second target. `ubuntu` stays exactly as it was; running both
    against the same host is what makes the v1→v2 delta measurable rather than
    merely asserted — the same system, scored with and without system-state
    evidence.

WHAT IT ADDS OVER `ubuntu`
    The `ubuntu` docstring names the limitation precisely: "Whole-system state
    checks (file permissions, kernel modules, running services) are OpenSCAP's
    domain, out of scope here". This target closes the first and third of
    those. It answers questions no config parser can:

      - /etc/shadow is mode 0644 (a property of the inode, in no file)
      - something is listening on 0.0.0.0:8080 (a property of a socket)

    On the VM built for this work the v1 path scores 7.5 from nginx.conf while
    both of those are true and unseen.

INPUT MODE
    The `path` is a filesystem ROOT, not a config file — `/` for the running
    host, or a mounted image. Detection therefore requires the markers of an
    Ubuntu root (/etc/os-release naming Ubuntu), not a filename.

    Sockets are only meaningful for a RUNNING system. Against a mounted image
    the exposure collector raises `CollectorUnavailable`, and this plugin lets
    that dimension go unassessed rather than reporting an image as listening
    on nothing — the distinction the whole dimension model rests on.
"""

from __future__ import annotations

import logging
from pathlib import Path

from config_assessment.core.collectors import (
    CollectorUnavailable, exposure, permissions)
from config_assessment.core.models import Directive, SystemProfile, TargetMetadata
from config_assessment.core.runtime import register_plugin
from config_assessment.core.target import (
    Target, CONFIDENCE_EXACT_FILENAME, CONFIDENCE_WEAK)
from config_assessment.plugins.ubuntu2204.rules import infer_profile

logger = logging.getLogger("ccss")

CHAINS: list = []


def _is_ubuntu_root(root: Path) -> bool:
    """Whether `root` looks like an Ubuntu filesystem root.

    Read from /etc/os-release rather than trusted from the path name, so a
    directory that merely happens to be called `ubuntu` is not mistaken for a
    system root.
    """
    try:
        text = (root / "etc/os-release").read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return False
    return "ubuntu" in text.lower()


class Ubuntu2204Plugin(Target):
    """Ubuntu 22.04 system state — permissions and network exposure (curated)."""

    def detect(self, path: str) -> bool:
        p = Path(path)
        return p.is_dir() and _is_ubuntu_root(p)

    def detection_confidence(self, path: str) -> int:
        # /etc/os-release naming Ubuntu is as unambiguous as an exact filename;
        # nothing else in the tree produces that string in that location.
        # A directory that is NOT an Ubuntu root never reaches here (detect
        # returned False), so the weak level is unreachable in practice and
        # kept only so the method is total.
        return CONFIDENCE_EXACT_FILENAME if _is_ubuntu_root(Path(path)) else CONFIDENCE_WEAK

    def parse_config(self, path: str) -> list[Directive]:
        """Observe system state and express it as directives.

        Named `parse_config` because that is the Target contract's name for
        "produce the directives for this input"; nothing in the contract
        requires them to come from parsing a file, which is exactly why
        collectors need no new pipeline.

        A collector that cannot look is logged and contributes nothing. It must
        NOT contribute an empty result: `[]` from a collector means "looked,
        found nothing", and manufacturing that from a failed observation is
        the one thing the dimension model exists to prevent.
        """
        root = Path(path)
        directives: list[Directive] = []

        for name, collect in (
            ("permissions", lambda: permissions.collect(root=root)),
            ("suid", lambda: permissions.collect_suid(root=root)),
            # `/` is the running host, and only then are live sockets the
            # sockets of the system being assessed. A mounted image's /proc is
            # empty or belongs to the scanning host, and reporting either as
            # the image's exposure would be a fabrication.
            ("exposure", lambda: exposure.collect()
                if root == Path("/") else _unavailable_image()),
        ):
            try:
                directives.extend(collect())
            except CollectorUnavailable as exc:
                logger.info("[ubuntu2204] %s not assessed: %s", name, exc)

        return directives

    def get_profile(self, directives: list[Directive]) -> SystemProfile:
        return infer_profile(directives)

    def metadata(self) -> TargetMetadata:
        return TargetMetadata(
            name="ubuntu2204",
            display_name="Ubuntu 22.04 system state (permissions, exposure)",
            version="22.04",
            benchmark_source="CIS Ubuntu 22.04 LTS Benchmark L1 Server "
                             "(system-state subset, curated)",
        )


def _unavailable_image():
    raise CollectorUnavailable(
        "Network exposure is only observable on a running system; a mounted "
        "image has no live sockets")


register_plugin(Ubuntu2204Plugin())
