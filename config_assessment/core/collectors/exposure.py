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

# Service identity by process name. Preferred over the port when available,
# because it survives the case the port-based rules cannot see: a datastore
# moved off its default port is still that datastore, and "security by
# non-standard port" is precisely the assumption an audit should not share.
#
# Keys are matched against /proc/<pid>/comm, which is the executable name
# truncated to 15 characters — hence `mysqld` and not `mysqld-server`.
_PROCESS_SERVICE: dict[str, str] = {
    "redis-server": "redis",
    "redis-sentinel": "redis",
    "mysqld": "mysql",
    "mariadbd": "mysql",
    "postgres": "postgresql",
    "mongod": "mongodb",
    "memcached": "memcached",
    "elasticsearch": "elasticsearch",
    "java": "",          # too generic to identify anything; fall back to port
    "dockerd": "docker",
}

# Service identity by conventional port, used when the process is unknown —
# the common case, since resolving it needs privilege the scan does not assume.
# A port is weaker evidence than a process name: it is a convention, not a
# fact about what is running. It is recorded as such in the evidence.
_PORT_SERVICE: dict[int, str] = {
    3306: "mysql",
    5432: "postgresql",
    6379: "redis",
    27017: "mongodb",
    9200: "elasticsearch",
    11211: "memcached",
    2375: "docker",
    2376: "docker",
}


def _service_of(process: str | None, port: int) -> tuple[str | None, str | None]:
    """Identify the service behind a socket, and say how confidently.

    Returns (service, basis) where basis is "process" or "port" — the console
    and the report need to distinguish an observed identity from an inferred
    one, and an operator dismissing a finding deserves to know which they are
    looking at.
    """
    if process:
        named = _PROCESS_SERVICE.get(process)
        if named:
            return named, "process"
    by_port = _PORT_SERVICE.get(port)
    if by_port:
        return by_port, "port"
    return None, None


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
    services: dict[str, dict] = {}

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

            # Second, PORT-INDEPENDENT directive for the same socket.
            #
            # The directive above encodes the port in its NAME, so it needs one
            # rule per port and misses a datastore moved off its default — the
            # documented gap this closes. Here the name is the QUESTION ("is
            # redis exposed?") and the value is the ANSWER, so a single rule
            # covers the service wherever it listens.
            #
            # Both are emitted because they answer different questions and the
            # engine de-duplicates by rule, not by socket: the port-named rules
            # carry per-port benchmark citations, this one carries the general
            # control. Two rules firing on one socket is two true statements.
            world_facing = _is_world_facing(address)
            service, basis = _service_of(process, port)
            if service:
                # Accumulated rather than emitted here: one service can hold
                # several sockets (dual-stack, or loopback plus wildcard), and
                # the exposure QUESTION has one answer per service. Deciding it
                # per socket would emit two contradictory findings for the same
                # service — "redis is exposed" and "redis is loopback" — and the
                # console would show both.
                prior = services.get(service)
                if prior is None or (world_facing and not prior["world_facing"]):
                    services[service] = {
                        "world_facing": world_facing,
                        "location": f"{proto}/{address}:{port}",
                        "process": process,
                        "pid": inode_pid.get(inode),
                        "identified_by": basis,
                    }

    # One verdict per service, and a world-facing binding decides it: a service
    # reachable from the network is exposed whether or not it also listens on
    # loopback. The reverse would let an extra loopback socket mask the finding.
    for service, seen_on in services.items():
        directives.append(Directive(
            name=f"exposed_service:{service}",
            # The VALUE is the classification, which is what makes the rule
            # port-independent: an exact-match join still works because the
            # collector, not the rule, does the deciding.
            value="world_facing" if seen_on["world_facing"] else "loopback",
            evidence={
                "kind": "listening_socket",
                "location": seen_on["location"],
                "process": seen_on["process"],
                "pid": seen_on["pid"],
                "world_facing": seen_on["world_facing"],
                "service": service,
                # Whether the identity was OBSERVED (process name) or INFERRED
                # (conventional port). An operator dismissing a finding
                # deserves to know which.
                "identified_by": seen_on["identified_by"],
            },
        ))

    return directives
