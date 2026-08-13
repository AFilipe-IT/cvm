#!/usr/bin/env python3
"""
scripts/sensitivity_fleet.py — build a synthetic multi-dimension fleet.

WHY THIS EXISTS. `scripts/sensitivity.py` needs hosts whose overall score is a
weighted mean of SEVERAL dimensions. Where a host has one assessed dimension,
renormalisation sends that dimension's weight to 1.0 and the overall equals its
score identically — every perturbation is then a no-op and the analysis is
vacuous, which is exactly what that script now refuses to report.

The reference database has only single-target config scans, so the fleet has to
be constructed. These are SYNTHETIC HOSTS, and the distinction matters for how
the result may be read: they establish that the AGGREGATION is insensitive to
the weights across a spread of dimension profiles. They are not a sample of
real systems and support no claim about real-world score distributions.

WHAT IS VARIED. Each host gets a different combination of permission flaws, so
the per-dimension scores differ between hosts and across dimensions. If every
host had the same profile the ranking would be all-ties and tau would again be
uninformative — so the flaws are deliberately staggered.

Run:
    python -m scripts.sensitivity_fleet --db /tmp/fleet.db
    python -m scripts.sensitivity  --db /tmp/fleet.db
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

# The mode each control expects. Every file a rule covers is listed, so a host
# profile is complete by construction: an omitted file would inherit the
# process umask and show up as a flaw nobody intended, which is how the first
# version of this fixture produced a "clean" host with a finding.
SECURE: dict[str, int] = {
    "etc/shadow": 0o640,
    "etc/gshadow": 0o640,
    "etc/passwd": 0o644,
    "etc/group": 0o644,
    "etc/ssh/sshd_config": 0o600,
    "etc/crontab": 0o600,
}

# (hostname, {relative path: mode}) — the OVERRIDES applied on top of SECURE.
# Different hosts violate a different number and severity of controls: the
# spread is what gives the ranking something to be stable about, since a fleet
# of identical profiles would be all-ties and tau would again say nothing.
FLEET: list[tuple[str, dict[str, int]]] = [
    ("host-clean",  {}),
    ("host-shadow", {"etc/shadow": 0o644}),
    ("host-sshd",   {"etc/ssh/sshd_config": 0o644}),
    ("host-cron",   {"etc/crontab": 0o644}),
    ("host-two",    {"etc/shadow": 0o644, "etc/ssh/sshd_config": 0o644}),
    ("host-three",  {"etc/shadow": 0o644, "etc/passwd": 0o666,
                     "etc/ssh/sshd_config": 0o644}),
    ("host-worst",  {"etc/shadow": 0o666, "etc/gshadow": 0o666,
                     "etc/passwd": 0o666, "etc/group": 0o666,
                     "etc/ssh/sshd_config": 0o666, "etc/crontab": 0o666}),
]


def _make_root(base: Path, modes: dict[str, int]) -> Path:
    """Materialise one Ubuntu root with the given permission profile."""
    (base / "etc/ssh").mkdir(parents=True, exist_ok=True)
    (base / "etc/os-release").write_text(
        'NAME="Ubuntu"\nVERSION="22.04.3 LTS"\nID=ubuntu\n')
    (base / "etc/passwd").write_text("root:x:0:0::/root:/bin/bash\n")
    (base / "etc/shadow").write_text("root:!:19000:0:99999:7:::\n")
    (base / "etc/group").write_text("root:x:0:\n")
    (base / "etc/gshadow").write_text("root:*::\n")
    (base / "etc/crontab").write_text("# m h dom mon dow user command\n")
    (base / "etc/ssh/sshd_config").write_text("Port 22\nPermitRootLogin no\n")
    # Secure baseline first, then this host's deliberate flaws over it.
    for rel, mode in {**SECURE, **modes}.items():
        (base / rel).chmod(mode)
    return base


def build(db_path: str, workdir: str | None = None) -> list[str]:
    from cli._discovery import _discover_plugins
    from config_assessment.core import runtime
    from config_assessment.core.db.database import Database
    from config_assessment.plugins.ubuntu2204.build_ubuntu2204 import run_build

    _discover_plugins()
    # Seed the ubuntu2204 rules into this database. Without them the scan finds
    # nothing and the fleet is a row of zeroes.
    run_build(db_path)

    db = Database(db_path)
    root = Path(workdir or tempfile.mkdtemp(prefix="cvm-fleet-"))
    scanned = []
    for name, modes in FLEET:
        host_root = _make_root(root / name, modes)
        result = runtime.scan(str(host_root), db)
        # runtime.scan only computes; persisting is a separate call, exactly as
        # in cli/commands/scan_cmds.py. Without it the fleet leaves no trace and
        # the analysis reads an empty database.
        db.save_scan_result(result)
        scanned.append(f"{name}: {len(result.issues)} findings, "
                       f"score {result.global_temporal_score} ({result.severity})")
    return scanned


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--workdir", default=None,
                    help="where to materialise the roots (default: a temp dir)")
    ap.add_argument("--fresh", action="store_true",
                    help="delete the database first")
    args = ap.parse_args()

    if args.fresh and Path(args.db).exists():
        Path(args.db).unlink()

    for line in build(args.db, args.workdir):
        print("  " + line)
    print(f"\n  fleet written to {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
