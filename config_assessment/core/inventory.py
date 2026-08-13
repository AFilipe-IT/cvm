"""
config_assessment/core/inventory.py
-----------------------------------
Host attribute collection.

WHY THIS IS NOT AN AGENT
    CVM is deployed as a single instance inside the organisation it assesses,
    so it already runs where the files are — `caspar watch` bind-mounts /etc
    for exactly this reason. Reading /etc/os-release and the machine's
    hostname is the same execution position and the same privilege as reading
    a config file, which the engine has always done. Adding an agent or an SSH
    fan-out would buy nothing here and would introduce credentials to manage.

WHAT IS IDENTITY AND WHAT IS AN ATTRIBUTE
    Everything this module collects is an ATTRIBUTE — it describes what a host
    currently looks like, and every field can change without the host becoming
    a different host. Identity lives in the `uuid` column, assigned once at
    first registration (see database.py::upsert_host).

    This distinction is the reason the module exists separately: it is what
    keeps a renamed machine from splitting its own history in two.

MISSING IS NOT EMPTY
    Every field is optional. A value that could not be read comes back as
    None, never as "" or "unknown", so the caller can tell "not collected"
    apart from "collected and genuinely absent" — the same distinction the
    dimension model draws between not_assessed and clean.
"""

from __future__ import annotations

import platform
import socket
from dataclasses import asdict, dataclass
from pathlib import Path

# The OS release file is read rather than shelled out to, so collection works
# identically inside a container with /etc mounted read-only.
OS_RELEASE = Path("/etc/os-release")


@dataclass
class HostAttributes:
    """What a host currently looks like. Every field may be None."""

    hostname: str | None = None
    ip_address: str | None = None
    os_family: str | None = None
    os_version: str | None = None
    kernel: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)


def collect(root: Path | str | None = None) -> HostAttributes:
    """Collect the attributes of the system this process runs on.

    `root` re-points the filesystem reads, which is what lets a scan of a
    mounted target directory describe *that* system rather than the container
    doing the reading.
    """
    base = Path(root) if root is not None else None
    os_release = (base / "etc/os-release") if base else OS_RELEASE

    family, version = _read_os_release(os_release)
    if base is not None:
        # A mounted root describes ANOTHER system. Its OS identity is readable
        # from the files, but its hostname, address and kernel are properties
        # of a running system this process is not inside — reporting the
        # collector's own would silently describe the wrong machine. Reading
        # etc/hostname would be no better: a cloned image carries a stale one.
        return HostAttributes(os_family=family, os_version=version)

    return HostAttributes(
        hostname=_hostname(),
        ip_address=_primary_ip(),
        os_family=family,
        os_version=version,
        kernel=platform.release(),
    )


def _read_os_release(path: Path) -> tuple[str | None, str | None]:
    """Parse ID and VERSION_ID out of an os-release file.

    The format is shell-assignment-like but is not shell: values may or may
    not be quoted, and unknown keys are common. Anything unparseable is
    skipped rather than raising — a malformed line must not cost the caller
    the fields that did parse.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None

    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        values[key.strip()] = raw.strip().strip('"').strip("'")

    return values.get("ID") or None, values.get("VERSION_ID") or None


def _hostname() -> str | None:
    try:
        return socket.gethostname() or None
    except OSError:
        return None


def _primary_ip() -> str | None:
    """The address the host would use to reach the outside world.

    Resolving the hostname is unreliable — it frequently returns 127.0.1.1 on
    Debian-family systems. Opening a UDP socket to a public address instead
    asks the routing table which source address it would pick; no packet is
    ever sent, so this works on an isolated network too.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(0.2)
        sock.connect(("192.0.2.1", 9))  # TEST-NET-1, guaranteed unroutable
        addr = sock.getsockname()[0]
        return addr if addr and not addr.startswith("127.") else None
    except OSError:
        return None
    finally:
        sock.close()
