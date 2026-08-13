"""
config_assessment/core/collectors/exposure.py
---------------------------------------------
Exposure dimension: which sockets are listening, and on which interface.

The distinction that matters is BINDING, not port number. A service on
127.0.0.1:6379 is reachable only from the machine itself; the same service on
0.0.0.0:6379 is reachable from the network. The port is identical and the risk
is not, and no configuration file states the resulting exposure — nginx's
`listen 8080;` says nothing about whether that is loopback or the world.

The VM built for this work has nginx bound to 0.0.0.0:8080 for exactly this
reason: v1 parses the config and scores 7.5 without ever noticing the socket.

WHY /proc/net/tcp AND NOT `ss` OR `netstat`
    Reading /proc needs no external binary, no elevated privilege, and no
    subprocess. It works in a minimal container where iproute2 is absent, and
    it cannot be defeated by a PATH manipulation. The format is stable kernel
    ABI.

    The cost is that /proc/net/tcp maps sockets to inodes, not to process
    names. Resolving the process means walking /proc/<pid>/fd, which needs
    privilege for other users' processes. When that fails the process comes
    back None — unknown, rather than guessed.

DIRECTIVE SHAPE
    listen:<proto>/<addr>:<port>   value "<process>" or "unknown"

    The address is in the NAME because it is what the rule is about: a rule
    concerns "something listening on 0.0.0.0:8080", and that must be the join
    key. The value carries the process, which is context for the operator.
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path

from config_assessment.core.collectors import CollectorUnavailable
from config_assessment.core.models import Directive

# Kernel TCP state 0A = TCP_LISTEN. Established connections are transient and
# say nothing about the host's attack surface, so only listeners are reported.
_TCP_LISTEN = "0A"

_PROC_SOURCES = (
    ("tcp", "net/tcp"),
    ("tcp6", "net/tcp6"),
)


def _parse_addr(hex_addr: str) -> tuple[str, int] | None:
    """'0100007F:1F90' → ('127.0.0.1', 8080).

    /proc renders the address as little-endian hex words, so the bytes are
    reversed per 4-byte group before being read as an address.
    """
    try:
        host_hex, port_hex = hex_addr.split(":")
        port = int(port_hex, 16)
    except (ValueError, AttributeError):
        return None

    try:
        raw = bytes.fromhex(host_hex)
    except ValueError:
        return None

    # Each 32-bit word is little-endian; IPv6 is four such words.
    reordered = b"".join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
    try:
        return str(ipaddress.ip_address(reordered)), port
    except ValueError:
        return None


def _is_world_facing(address: str) -> bool:
    """Whether binding to this address exposes the service beyond the host.

    The wildcard addresses (0.0.0.0, ::) accept on every interface. Anything
    else is a specific interface: loopback is host-only, and a concrete LAN
    address is reachable from that network — reported as exposed, because it
    is, even though it is narrower than a wildcard.

    IPv4-mapped v6 addresses (::ffff:127.0.0.1) are unwrapped first. Python
    reports `is_loopback` False for those — the v6 address itself is not in
    ::1/128 — but a service bound there is bound to 127.0.0.1 and is not
    reachable off-host. Left unwrapped it would be a false positive, which is
    the direction that costs the dimension its credibility.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return not (ip.is_loopback or ip.is_link_local)


def _inode_to_pid(proc: Path) -> dict[str, int]:
    """Socket inode → owning pid, by walking /proc/<pid>/fd.

    Best-effort: another user's process descriptors are unreadable without
    privilege, and those simply do not appear in the map. The caller reports
    the process as unknown rather than inventing one.
    """
    mapping: dict[str, int] = {}
    try:
        entries = [e for e in proc.iterdir() if e.name.isdigit()]
    except (PermissionError, OSError):
        return mapping

    for entry in entries:
        try:
            for fd in (entry / "fd").iterdir():
                try:
                    link = os.readlink(fd)
                except (PermissionError, OSError):
                    continue
                if link.startswith("socket:["):
                    mapping[link[8:-1]] = int(entry.name)
        except (PermissionError, OSError, FileNotFoundError):
            continue
    return mapping


def _process_name(proc: Path, pid: int | None) -> str | None:
    if pid is None:
        return None
    try:
        return (proc / str(pid) / "comm").read_text().strip() or None
    except (PermissionError, OSError, FileNotFoundError):
        return None


def collect(proc_root: str | Path = "/proc",
            resolve_process: bool = True) -> list[Directive]:
    """Observe listening TCP sockets.

    Raises `CollectorUnavailable` when /proc/net is unreadable — on a mounted
    disk image, for instance, where sockets have no meaning at all. Returning
    an empty list there would assert that the system listens on nothing, which
    is a claim about a running system that is not running.
    """
    proc = Path(proc_root)
    available = [(p, proc / rel) for p, rel in _PROC_SOURCES if (proc / rel).exists()]
    if not available:
        raise CollectorUnavailable(
            f"No readable socket table under '{proc}'; network exposure was "
            "not assessed (a mounted image has no live sockets)")

    inode_pid = _inode_to_pid(proc) if resolve_process else {}
    directives: list[Directive] = []
    seen: set[str] = set()

    for proto, path in available:
        try:
            lines = path.read_text().splitlines()[1:]
        except (PermissionError, OSError):
            continue

        for line in lines:
            fields = line.split()
            if len(fields) < 10 or fields[3] != _TCP_LISTEN:
                continue

            parsed = _parse_addr(fields[1])
            if parsed is None:
                continue
            address, port = parsed
            inode = fields[9]

            process = _process_name(proc, inode_pid.get(inode))
            key = f"{proto}/{address}:{port}"
            if key in seen:
                continue
            seen.add(key)

            directives.append(Directive(
                name=f"listen:{proto}/{address}:{port}",
                value=process or "unknown",
                evidence={
                    "kind": "listening_socket",
                    "location": f"{proto}/{address}:{port}",
                    "process": process,
                    "pid": inode_pid.get(inode),
                    # Precomputed so a rule can be written against exposure
                    # without every rule author re-deriving what counts as
                    # world-facing.
                    "world_facing": _is_world_facing(address),
                },
            ))

    return directives
