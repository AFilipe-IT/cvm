"""
plugins/ubuntu2204/rules.py
---------------------------
Curated rules for the SYSTEM-STATE controls of the CIS Ubuntu 22.04 Benchmark
(Level 1 Server) — the controls expressed as a property of an inode or a
socket rather than as a value in a config file.

These are precisely the controls the `ubuntu` target documents as out of
scope: "Whole-system state checks (file permissions, kernel modules, running
services) are OpenSCAP's domain". They are in scope here.

WHY bad_value IS AN EXACT STRING
    The engine joins on `(target, directive, value)`, so a rule fires on an
    exact observed value, not on a predicate. CIS §6.1 states the permissions
    controls as "mode 0640 or more restrictive", which is a set — enumerated
    here as the loose modes that actually occur, worst first. That is honest
    about what is covered: a mode not enumerated is not silently passed, it is
    surfaced as an unknown directive by the coverage machinery (v1's
    unknown-directive detection), which is the mechanism for exactly this.

ENTRIES: (directive, bad_value, good_value, section, ac, c, i, a, just, rec)
  matching the curated build's contract; AV=N, Au=N are fixed by that build.
"""

from __future__ import annotations

from config_assessment.core.models import Directive, SystemProfile

# ── /etc/shadow and /etc/gshadow (CIS §6.1.2, §6.1.4) ───────────────────────
# The hashed passwords. World- or group-readable means any local account can
# copy the hashes and crack them offline, so C is Complete: the whole point of
# shadowing is that these are not readable.
_SHADOW = [
    ("file_mode:/etc/shadow", "0644", "0640", "CIS Ubuntu 6.1.2",
     "L", "C", "N", "N",
     "World-readable /etc/shadow exposes every account's password hash to any "
     "local user, who can crack them offline at leisure — defeating the entire "
     "purpose of a shadowed password file.",
     "Run: chmod 0640 /etc/shadow"),
    ("file_mode:/etc/shadow", "0666", "0640", "CIS Ubuntu 6.1.2",
     "L", "C", "C", "N",
     "World-writable /etc/shadow lets any local user replace root's password "
     "hash and take the account outright.",
     "Run: chmod 0640 /etc/shadow"),
    ("file_mode:/etc/shadow", "0755", "0640", "CIS Ubuntu 6.1.2",
     "L", "C", "N", "N",
     "World-readable /etc/shadow exposes every account's password hash to "
     "offline cracking.",
     "Run: chmod 0640 /etc/shadow"),
    ("file_owner:/etc/shadow", "root:root", "root:shadow", "CIS Ubuntu 6.1.2",
     "H", "P", "N", "N",
     "Ubuntu expects /etc/shadow to be group-owned by 'shadow'; a different "
     "group ownership usually means the file was restored or edited by hand "
     "and the shipped access model no longer holds.",
     "Run: chown root:shadow /etc/shadow"),
    ("file_mode:/etc/gshadow", "0644", "0640", "CIS Ubuntu 6.1.4",
     "L", "C", "N", "N",
     "World-readable /etc/gshadow exposes group password hashes to offline "
     "cracking, which can grant group membership and its privileges.",
     "Run: chmod 0640 /etc/gshadow"),
    ("file_mode:/etc/gshadow", "0666", "0640", "CIS Ubuntu 6.1.4",
     "L", "C", "C", "N",
     "World-writable /etc/gshadow lets a local user grant themselves membership "
     "of any group, including privileged ones.",
     "Run: chmod 0640 /etc/gshadow"),
]

# ── /etc/passwd and /etc/group (CIS §6.1.1, §6.1.3) ─────────────────────────
# These are legitimately world-READABLE (0644 is correct — name resolution
# needs it), so only WRITABLE modes are findings. A rule flagging 0644 here
# would be a false positive on every correctly configured Ubuntu system.
_PASSWD = [
    ("file_mode:/etc/passwd", "0666", "0644", "CIS Ubuntu 6.1.1",
     "L", "P", "C", "N",
     "World-writable /etc/passwd lets any local user add an account with UID 0 "
     "or clear root's password field, escalating to full system control.",
     "Run: chmod 0644 /etc/passwd"),
    ("file_mode:/etc/passwd", "0777", "0644", "CIS Ubuntu 6.1.1",
     "L", "P", "C", "N",
     "World-writable /etc/passwd lets any local user create a UID 0 account.",
     "Run: chmod 0644 /etc/passwd"),
    ("file_mode:/etc/group", "0666", "0644", "CIS Ubuntu 6.1.3",
     "L", "N", "C", "N",
     "World-writable /etc/group lets any local user add themselves to a "
     "privileged group such as sudo or adm.",
     "Run: chmod 0644 /etc/group"),
]

# ── sshd_config file permissions (CIS §5.1.1) ───────────────────────────────
# Distinct from the `ssh` target, which reads the DIRECTIVES inside this file.
# This is the file's own mode — the same file, a different kind of evidence,
# and a good illustration of why the dimension axis is the nature of the
# evidence rather than the subject of the rule.
_SSHD = [
    ("file_mode:/etc/ssh/sshd_config", "0644", "0600", "CIS Ubuntu 5.1.1",
     "M", "P", "N", "N",
     "A world-readable sshd_config discloses the exact SSH hardening in place "
     "— permitted authentication methods, allowed users, listening port — "
     "letting an attacker target the weakest configured path.",
     "Run: chmod 0600 /etc/ssh/sshd_config"),
    ("file_mode:/etc/ssh/sshd_config", "0666", "0600", "CIS Ubuntu 5.1.1",
     "L", "C", "C", "C",
     "A world-writable sshd_config lets a local user enable root login or "
     "password authentication and take the host on the next restart.",
     "Run: chmod 0600 /etc/ssh/sshd_config"),
]

# ── cron (CIS §5.1.2–5.1.8) ─────────────────────────────────────────────────
# Cron runs its jobs as root, so write access to any of these directories is
# root-equivalent on a schedule.
_CRON = [
    ("file_mode:/etc/crontab", "0666", "0600", "CIS Ubuntu 5.1.2",
     "L", "C", "C", "C",
     "A world-writable /etc/crontab lets any local user schedule a command "
     "that cron will run as root.",
     "Run: chmod 0600 /etc/crontab"),
    ("file_mode:/etc/cron.d", "0777", "0700", "CIS Ubuntu 5.1.7",
     "L", "C", "C", "C",
     "A world-writable /etc/cron.d lets any local user drop in a job that runs "
     "as root.",
     "Run: chmod 0700 /etc/cron.d"),
    ("file_mode:/etc/cron.daily", "0777", "0700", "CIS Ubuntu 5.1.4",
     "L", "C", "C", "C",
     "A world-writable /etc/cron.daily lets any local user schedule a script "
     "that runs as root every day.",
     "Run: chmod 0700 /etc/cron.daily"),
    ("file_mode:/etc/cron.hourly", "0777", "0700", "CIS Ubuntu 5.1.3",
     "L", "C", "C", "C",
     "A world-writable /etc/cron.hourly lets any local user schedule a script "
     "that runs as root every hour.",
     "Run: chmod 0700 /etc/cron.hourly"),
]

# ── bootloader (CIS §1.4.1) ─────────────────────────────────────────────────
_BOOT = [
    ("file_mode:/boot/grub/grub.cfg", "0644", "0600", "CIS Ubuntu 1.4.1",
     "H", "P", "N", "N",
     "A readable grub.cfg discloses the boot configuration and any password "
     "hash protecting the bootloader, which can be cracked offline to gain "
     "single-user root access at the console.",
     "Run: chmod 0600 /boot/grub/grub.cfg"),
]

# ── network exposure ────────────────────────────────────────────────────────
# The directive NAME carries the binding, so a rule is written against a
# specific world-facing address:port. The value is the process holding the
# socket; `unknown` is the honest value when /proc/<pid>/fd is unreadable, and
# the rules must fire on it — a finding that only appears when running as root
# would be a finding that disappears exactly when the scan is least privileged.
#
# Only administrative and datastore ports are enumerated: a public web server
# on 0.0.0.0:80 is the intended configuration, and flagging it would be the
# kind of false positive that trains an operator to ignore the tool.
#
# KNOWN LIMITATION — coverage is by PORT, not by the `world_facing` flag the
# collector computes. A datastore on a non-standard port is observed (it
# appears among the scanned directives, with `world_facing` set) but matches no
# rule, so it is not scored. Closing that needs either a predicate rule type —
# the engine matches exact values, by design, because that is what makes a
# score reproducible from the stated rule — or process-name resolution, which
# requires privilege the scan does not assume. The gap is real and is stated
# here rather than hidden behind an enumeration that looks exhaustive.
def _exposure_entries() -> list[tuple]:
    services = [
        ("3306", "MySQL/MariaDB", "CIS Ubuntu 3.1.1", "C", "C", "P",
         "a database server exposed to the network, where every "
         "authentication attempt is remote and unthrottled"),
        ("5432", "PostgreSQL", "CIS Ubuntu 3.1.1", "C", "C", "P",
         "a database server exposed to the network"),
        ("6379", "Redis", "CIS Ubuntu 3.1.1", "C", "C", "C",
         "a Redis instance exposed to the network — Redis is unauthenticated "
         "by default, and a reachable instance is routinely trivial to turn "
         "into remote code execution"),
        ("27017", "MongoDB", "CIS Ubuntu 3.1.1", "C", "C", "P",
         "a MongoDB instance exposed to the network"),
        ("9200", "Elasticsearch", "CIS Ubuntu 3.1.1", "C", "C", "P",
         "an Elasticsearch node exposed to the network, typically holding "
         "logs or indexed documents with no authentication"),
        ("11211", "Memcached", "CIS Ubuntu 3.1.1", "C", "P", "C",
         "a Memcached instance exposed to the network, which is both readable "
         "and usable as a high-amplification DDoS reflector"),
        ("2375", "Docker API", "CIS Ubuntu 3.1.1", "C", "C", "C",
         "the unauthenticated Docker daemon API, which grants root on the "
         "host to anyone who can reach it"),
    ]
    entries = []
    for port, label, section, c, i, a, phrase in services:
        for address in ("0.0.0.0", "::"):
            proto = "tcp" if address == "0.0.0.0" else "tcp6"
            entries.append((
                f"listen:{proto}/{address}:{port}", "unknown", "127.0.0.1", section,
                "L", c, i, a,
                f"{label} is bound to {address}, making it reachable from any "
                f"network the host is attached to — {phrase}. The service's own "
                "configuration file cannot reveal this: the same directive "
                "produces a loopback-only or a world-facing socket depending on "
                "the address it binds.",
                f"Bind {label} to 127.0.0.1, or restrict access with a host "
                f"firewall rule for port {port}."))
    return entries


_EXPOSURE = _exposure_entries()

ENTRIES = _SHADOW + _PASSWD + _SSHD + _CRON + _BOOT + _EXPOSURE
ABSENCE_RULES: list = []


def infer_profile(directives: list[Directive]) -> SystemProfile:
    """System-state controls on a server: AV=N, Au=N, worst case.

    Matches the `ubuntu` target's reasoning and what the curated build fixes.
    Permissions findings are locally exploitable and exposure findings are
    remotely exploitable; the profile is the system-global worst case, and
    per-control nuance is carried by AC in the entries above.
    """
    return SystemProfile(av="N", au="N")
