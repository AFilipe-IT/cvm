"""
plugins/ubuntu2204/build_ubuntu2204.py
--------------------------------------
Seed the curated Ubuntu 22.04 system-state ruleset into the DB. Deterministic —
no LLM, no network (see build/curated_build.py).

Usage:
    python3 -m config_assessment.plugins.ubuntu2204.build_ubuntu2204 [--db ccss.db]
"""

from __future__ import annotations

import argparse

from config_assessment.build.curated_build import run_curated_build
from config_assessment.plugins.ubuntu2204.rules import ABSENCE_RULES, ENTRIES


def run_build(db_path: str = "ccss.db") -> dict:
    from config_assessment.plugins.ubuntu2204 import Ubuntu2204Plugin
    return run_curated_build(
        meta=Ubuntu2204Plugin().metadata(),
        entries=ENTRIES,
        absence_rules=ABSENCE_RULES,
        chains_json=None,
        db_path=db_path,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="ccss.db")
    stats = run_build(ap.parse_args().db)
    print(f"ubuntu2204: {stats['misconfigs']} rules seeded")
