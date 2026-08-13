"""
config_assessment/core/collectors/permissions.py
------------------------------------------------
Permissions dimension: file modes, ownership, and SUID/SGID binaries.

Answers a question the configuration dimension structurally cannot. CIS Ubuntu
22.04 §6.1 requires `/etc/shadow` to be mode 0640 or stricter; that is a
property of the inode, not of any directive in any file, so no config parser
will ever see it. The v1 engine scanning the VM built for this work scores 7.5
while `/etc/shadow` sits at 0644 — not because the rule is wrong but because
nothing was looking at inodes.

DIRECTIVE SHAPE
    file_mode:<path>   value "0644"          — the octal permission bits
    file_owner:<path>  value "root:shadow"   — user:group

    Two directives per path rather than one combined, because the benchmark
    states them as separate controls with different severities: a
    world-readable shadow file and a wrongly-owned one are different failures
    and want different scores.

WHY OCTAL STRINGS AND NOT INTEGERS
    `0644` and `644` are the same number and different strings, and the
    knowledge base joins on strings. Modes are always normalised to four
    octal digits so a rule written as `0644` matches, which is also how the
    benchmark and `stat -c %a` conventionally render them.
"""

from __future__ import annotations

import grp
import os
import pwd
import stat as stat_module
from pathlib import Path

from config_assessment.core.collectors import CollectorUnavailable
from config_assessment.core.models import Directive

# Paths CIS Ubuntu 22.04 L1 Server states permission controls for (§6.1).
# Deliberately a curated list, not a filesystem walk: a walk would produce
# tens of thousands of directives with no rules behind them, and the scan cost
# would be unbounded on a real host. Every path here has a benchmark control.
AUDITED_PATHS: tuple[str, ...] = (
    "/etc/passwd",
    "/etc/shadow",
    "/etc/group",
    "/etc/gshadow",
    "/etc/passwd-",
    "/etc/shadow-",
    "/etc/group-",
    "/etc/gshadow-",
    "/etc/ssh/sshd_config",
    "/etc/crontab",
    "/etc/cron.hourly",
    "/etc/cron.daily",
    "/etc/cron.weekly",
    "/etc/cron.monthly",
    "/etc/cron.d",
    "/boot/grub/grub.cfg",
)


def _mode(st: os.stat_result) -> str:
    """Permission bits as four octal digits ('0644')."""
    return format(stat_module.S_IMODE(st.st_mode), "04o")


def _owner(st: os.stat_result) -> str:
    """'user:group', falling back to numeric ids.

    A uid with no passwd entry is reported as the number rather than skipped:
    a file owned by a user that no longer exists is itself worth seeing, and
    silently dropping it would hide exactly that.
    """
    try:
        user = pwd.getpwuid(st.st_uid).pw_name
    except (KeyError, OSError):
        user = str(st.st_uid)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except (KeyError, OSError):
        group = str(st.st_gid)
    return f"{user}:{group}"


def collect(root: str | Path | None = None,
            paths: tuple[str, ...] = AUDITED_PATHS) -> list[Directive]:
    """Observe permissions on the audited paths.

    `root` prefixes every path, so a mounted filesystem can be assessed from
    outside — the same image the scanner is not running inside.

    A path that does not exist yields NO directive. That is not the same as a
    clean result: absence is reported by the benchmark's own absence rules if
    the file is required, and inventing a directive for a missing file would
    assert an observation that never happened.
    """
    base = Path(root) if root is not None else None
    if base is not None and not base.is_dir():
        raise CollectorUnavailable(f"Root '{base}' is not a readable directory")

    directives: list[Directive] = []
    unreadable = 0

    for path in paths:
        target = (base / path.lstrip("/")) if base is not None else Path(path)
        try:
            st = target.lstat()
        except FileNotFoundError:
            continue
        except (PermissionError, OSError):
            # Counted, not silently skipped: if nothing at all could be read
            # the collector reports unavailable rather than clean.
            unreadable += 1
            continue

        display = str(path)
        evidence = {
            "kind": "file_metadata",
            "location": display,
            "mode": _mode(st),
            "owner": _owner(st).split(":")[0],
            "group": _owner(st).split(":")[1],
        }
        directives.append(Directive(
            name=f"file_mode:{display}", value=_mode(st),
            source_file=display, evidence=evidence))
        directives.append(Directive(
            name=f"file_owner:{display}", value=_owner(st),
            source_file=display, evidence=evidence))

    if not directives and unreadable:
        raise CollectorUnavailable(
            f"None of the {unreadable} audited path(s) present could be read; "
            "permissions were not assessed")
    return directives


def collect_suid(root: str | Path | None = None,
                 search_paths: tuple[str, ...] = ("/usr/bin", "/usr/sbin",
                                                  "/bin", "/sbin")) -> list[Directive]:
    """SUID/SGID binaries in the standard binary directories.

    Reported as an inventory (`suid_binary:<path>`) rather than judged here:
    which SUID binaries are legitimate is a policy question the knowledge base
    answers, and a collector that decided it would be duplicating the rules.
    """
    base = Path(root) if root is not None else None
    directives: list[Directive] = []

    for directory in search_paths:
        d = (base / directory.lstrip("/")) if base is not None else Path(directory)
        if not d.is_dir():
            continue
        try:
            entries = sorted(d.iterdir())
        except (PermissionError, OSError):
            continue

        for entry in entries:
            try:
                st = entry.lstat()
            except (FileNotFoundError, PermissionError, OSError):
                continue
            if not stat_module.S_ISREG(st.st_mode):
                continue
            bits = st.st_mode & (stat_module.S_ISUID | stat_module.S_ISGID)
            if not bits:
                continue

            display = f"{directory}/{entry.name}"
            kind = ("suid+sgid" if bits == (stat_module.S_ISUID | stat_module.S_ISGID)
                    else "suid" if bits & stat_module.S_ISUID else "sgid")
            directives.append(Directive(
                name=f"suid_binary:{display}", value=kind, source_file=display,
                evidence={"kind": "file_metadata", "location": display,
                          "mode": _mode(st), "owner": _owner(st).split(":")[0],
                          "group": _owner(st).split(":")[1]}))
    return directives
