#!/usr/bin/env python3
"""
scripts/agreement.py — do the curated rules agree with the benchmark?

THE QUESTION THIS ANSWERS. The `ubuntu2204` target's rules were written by hand
against CIS Ubuntu 22.04. A reader is entitled to ask whether "written by hand
against CIS" means the same thing as "what CIS actually says" — a curated rule
that demands the wrong mode is worse than no rule, because it reports a
compliant host as broken with full confidence.

The SCAP Security Guide publishes the same controls machine-readably: a
`template:` block naming a file and its expected mode, with per-product
overrides. Where a curated rule and an SSG rule speak about the same object,
their expected values can be compared directly. That comparison is this script.

WHY THE JOIN IS NOT ON THE CIS SECTION NUMBER
    The obvious key — the "CIS Ubuntu 6.1.2" reference each curated rule
    carries — DOES NOT WORK, and using it would manufacture a false result.
    The curated references and SSG's `controls/cis_ubuntu2204.yml` come from
    different CIS revisions, which renumbered the sections: curated 6.1.2 is
    /etc/shadow's mode, while SSG's 6.1.2 is a different control entirely.
    Joining on it would report disagreement everywhere and measure nothing but
    the renumbering.

    So the join is on WHAT IS OBSERVED — the (kind, path) pair. Both sides name
    a filesystem object and an expected mode or owner; that pair is the thing
    two sources can genuinely agree or disagree about, and it survives any
    renumbering.

WHAT IS REPORTED
    agree       both name the same expected value
    disagree    both cover the object, expected values differ — the finding
                that matters, listed individually and never just counted
    curated-only  no SSG rule covers it (often deliberate: the `listen:` rules
                have no SSG equivalent, since network exposure is observed from
                sockets, not files)

    Coverage and agreement are reported SEPARATELY. A curated rule with no SSG
    counterpart is not evidence of error, and folding it into a single
    percentage would hide which of the two things went wrong.

Run:
    python -m scripts.agreement --archive path/to/scap-security-guide-*.tar.bz2
    python -m scripts.agreement --archive ... --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Curated rule kind -> the SSG template that expresses the same observation.
# Only these can be compared; a curated `listen:` rule has no file-template
# counterpart by construction, and is reported as uncovered rather than
# silently dropped.
KIND_TO_TEMPLATE = {
    "file_mode": "file_permissions",
    "file_owner": "file_owner",
    "file_group": "file_groupowner",
}


def _normalise_path(p: str) -> str:
    """SSG writes directories with a trailing slash, the curated rules do not.

    Only the trailing slash is stripped. Nothing else is normalised: two
    genuinely different paths must stay different, or the join would pair
    rules that speak about different files.
    """
    return p.rstrip("/") or "/"


def _curated_index() -> tuple[dict[tuple[str, str], dict], list[dict]]:
    """Curated rules keyed by (kind, path), keeping the STRICTEST expectation.

    A curated entry is (identifier, bad_value, good_value, ref, ...) and the
    same object appears several times — once per bad value it rejects. They all
    declare the same good value, so the first wins; a differing good value
    inside the curated set is itself a defect and is surfaced as such.
    """
    from config_assessment.plugins.ubuntu2204 import rules as cur

    index: dict[tuple[str, str], dict] = {}
    internal_conflicts: list[dict] = []

    for entry in cur.ENTRIES:
        identifier, _bad, good, ref = entry[0], entry[1], entry[2], entry[3]
        if ":" not in identifier:
            continue
        kind, _, path = identifier.partition(":")
        if kind not in KIND_TO_TEMPLATE:
            continue  # `listen:` and friends — no file-template counterpart
        key = (kind, _normalise_path(path))
        if key in index and index[key]["good"] != good:
            internal_conflicts.append(
                {"identifier": identifier,
                 "values": [index[key]["good"], good]})
            continue
        index.setdefault(key, {"good": good, "ref": ref,
                               "identifier": identifier})

    return index, internal_conflicts


def _ssg_index(archive_path: str, product: str) -> dict[tuple[str, str], dict]:
    """Deterministic SSG rules keyed the same way.

    Only `deterministic` rules take part: a rule whose expected value the LLM
    would have to recover from prose is not ground truth, and comparing against
    it would measure the extractor, not the benchmark.
    """
    from config_assessment.fetch.ssg_source import SSGArchive

    template_to_kind = {v: k for k, v in KIND_TO_TEMPLATE.items()}
    out: dict[tuple[str, str], dict] = {}
    for r in SSGArchive(archive_path).resolve(product):
        if not r.deterministic or not r.identifier or not r.good_value:
            continue
        kind = template_to_kind.get(r.template)
        if kind is None:
            continue
        # A Jinja macro that this module deliberately does not render is not a
        # path and cannot be joined on.
        if "{{{" in r.identifier:
            continue
        out[(kind, _normalise_path(r.identifier))] = {
            "good": r.good_value,
            "control_id": r.control_id,
            "rule_name": r.rule_name,
            "cce": r.cce,
        }
    return out


def _values_match(kind: str, curated: str, ssg: str) -> bool:
    """Whether two expected values say the same thing.

    Modes are compared numerically so that '0640' and '640' are one value, not
    two — the leading zero is notation, not substance. Owners are compared as
    written, except that SSG states them as numeric ids ('0') where the curated
    rules may say 'root'; that pair is the one alias worth encoding, and any
    other difference stays a disagreement rather than being explained away.
    """
    c, s = curated.strip(), ssg.strip()
    if kind == "file_mode":
        try:
            return int(c, 8) == int(s, 8)
        except ValueError:
            return c == s
    if kind in ("file_owner", "file_group"):
        # The two sources model ownership differently and the comparison must
        # respect that rather than call it a disagreement. A curated rule packs
        # owner AND group into one check ("root:shadow"); SSG splits them into
        # file_owner and file_groupowner, so its file_owner value is the owner
        # alone. Comparing the pair against the scalar would report a conflict
        # where both say the owner is root.
        #
        # Only the owner half is compared here, which is all the SSG rule
        # states. The group half is left unverified rather than assumed
        # correct: SSG carries it in an unrendered Jinja macro this pipeline
        # deliberately does not evaluate, so there is nothing to compare it to,
        # and it is counted as such in `group_unverified`.
        owner = c.split(":", 1)[0]
        alias = {"root": "0"}
        return alias.get(owner, owner) == alias.get(s, s)
    return c == s


def run(archive_path: str, product: str) -> dict:
    curated, internal_conflicts = _curated_index()
    ssg = _ssg_index(archive_path, product)

    agree, disagree, uncovered, group_unverified = [], [], [], []
    for key, cinfo in sorted(curated.items()):
        kind, path = key
        sinfo = ssg.get(key)
        if sinfo is None:
            uncovered.append({"identifier": cinfo["identifier"],
                              "curated_value": cinfo["good"],
                              "curated_ref": cinfo["ref"]})
            continue
        # A curated owner rule that also names a group has a half SSG's
        # file_owner template cannot speak to. Recorded so the agreement figure
        # is not read as covering more than it does.
        if kind == "file_owner" and ":" in cinfo["good"]:
            group_unverified.append({
                "identifier": cinfo["identifier"],
                "curated_group": cinfo["good"].split(":", 1)[1],
            })
        row = {
            "identifier": cinfo["identifier"],
            "curated_value": cinfo["good"],
            "ssg_value": sinfo["good"],
            "ssg_control": sinfo["control_id"],
            "ssg_rule": sinfo["rule_name"],
            "cce": sinfo["cce"],
        }
        (agree if _values_match(kind, cinfo["good"], sinfo["good"])
         else disagree).append(row)

    compared = len(agree) + len(disagree)
    return {
        "product": product,
        "archive": Path(archive_path).name,
        "curated_comparable": len(curated),
        "ssg_deterministic_file_rules": len(ssg),
        "compared": compared,
        # Two separate denominators on purpose: agreement is over what could be
        # compared, coverage is over what the curated set claims.
        "agreement_rate": round(100.0 * len(agree) / compared, 1) if compared else None,
        "coverage_rate": round(100.0 * compared / len(curated), 1) if curated else None,
        "agree": agree,
        "disagree": disagree,
        "uncovered": uncovered,
        "group_unverified": group_unverified,
        "internal_conflicts": internal_conflicts,
    }


def report(d: dict) -> None:
    print("\n" + "=" * 70)
    print("  RULE AGREEMENT — curated ubuntu2204 vs SCAP Security Guide")
    print("=" * 70)
    print(f"  archive: {d['archive']} · product: {d['product']}")
    print(f"  curated rules comparable by (kind, path) : {d['curated_comparable']}")
    print(f"  SSG deterministic file rules             : {d['ssg_deterministic_file_rules']}")
    print(f"  joined                                   : {d['compared']}")
    print()

    if d["agree"]:
        print(f"  AGREE ({len(d['agree'])})")
        for r in d["agree"]:
            print(f"    {r['identifier']:<34} {r['curated_value']:<8} "
                  f"= {r['ssg_value']:<8} [{r['ssg_control']}]")
        print()

    if d["disagree"]:
        print(f"  DISAGREE ({len(d['disagree'])})  ← each of these is a defect in one source")
        for r in d["disagree"]:
            print(f"    {r['identifier']:<34} curated={r['curated_value']:<8} "
                  f"ssg={r['ssg_value']:<8} [{r['ssg_control']} {r['ssg_rule']}]")
        print()

    if d["uncovered"]:
        print(f"  NOT IN SSG ({len(d['uncovered'])})  ← coverage, not error")
        for r in d["uncovered"]:
            print(f"    {r['identifier']:<34} curated={r['curated_value']:<8} "
                  f"({r['curated_ref']})")
        print()

    if d["group_unverified"]:
        print(f"  GROUP HALF UNVERIFIED ({len(d['group_unverified'])})  ← "
              f"owner compared, group has no SSG counterpart")
        for r in d["group_unverified"]:
            print(f"    {r['identifier']:<34} group={r['curated_group']}")
        print()

    if d["internal_conflicts"]:
        print(f"  CURATED SET CONTRADICTS ITSELF ({len(d['internal_conflicts'])})")
        for r in d["internal_conflicts"]:
            print(f"    {r['identifier']}: {r['values']}")
        print()

    if d["agreement_rate"] is not None:
        print(f"  agreement over joined rules : {d['agreement_rate']}%")
        print(f"  joinable coverage           : {d['coverage_rate']}%")
    else:
        print("  nothing could be joined — no agreement figure is defensible")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", required=True,
                    help="path to a scap-security-guide-*.tar.bz2 release")
    ap.add_argument("--product", default="ubuntu2204")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    d = run(args.archive, args.product)
    if args.json:
        json.dump(d, sys.stdout, indent=2)
        print()
    else:
        report(d)
    # Disagreement is a result to read, not a crash: exit 0 so the script can
    # run in the evaluation pipeline without a defect aborting the whole run.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
