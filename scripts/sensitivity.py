#!/usr/bin/env python3
"""
scripts/sensitivity.py — weight sensitivity analysis for the CVM scoring model.

THE QUESTION THIS ANSWERS. `DIMENSION_WEIGHTS` is a policy input, not a
measurement: nobody derived 0.28 / 0.24 / 0.28 / 0.10 / 0.06 / 0.04 from data,
they were chosen. A reader is entitled to ask what the scores would have been
had they been chosen slightly differently — and if a ±10% wobble reorders which
host is worst, the ranking is an artefact of that choice rather than a finding
about the hosts.

WHAT IS MEASURED
  1. Score stability   — how far the overall moves under perturbed weights.
  2. Ranking stability — whether the ORDER of hosts survives, which is what an
     operator actually acts on. Reported as Kendall's tau-b against the
     ranking produced by the declared weights.
  3. Severity-band flips — how often a perturbation moves a host across a
     band boundary, since the band is what the console shows.

Ranking matters more than the absolute number here. An operator triages the
worst host first; if every perturbation returns the same order, the ordering is
robust even where the third decimal is not.

METHOD. Deterministic grid, not a random sample: every dimension's weight is
independently scaled by ±10% and the posture recomputed with the engine's own
`aggregate_posture` (never a reimplementation — a reimplementation that drifts
would measure the wrong function). Weights are renormalised over assessed
dimensions by that same function, exactly as in production.

Run:
    python -m scripts.sensitivity                 # human-readable
    python -m scripts.sensitivity --json          # machine-readable
    python -m scripts.sensitivity --delta 0.2     # ±20% instead of ±10%
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
DB = str(ROOT / "ccss.db")


# ── ranking comparison ─────────────────────────────────────────────────

def kendall_tau_b(a: list[float], b: list[float]) -> float:
    """Kendall's tau-b between two score vectors, ties handled.

    Written out rather than pulled from scipy: the evaluation pipeline has no
    scipy dependency, and adding one for a dozen lines of pair counting would
    make the thesis numbers harder to reproduce, not easier.

    Returns 1.0 for identical orderings, -1.0 for exactly reversed. tau-b is
    the tie-corrected variant, which matters because scores are rounded to one
    decimal and ties are therefore common.
    """
    n = len(a)
    if n < 2:
        return 1.0

    concordant = discordant = ties_a = ties_b = 0
    for i, j in itertools.combinations(range(n), 2):
        da = a[i] - a[j]
        db = b[i] - b[j]
        if da == 0 and db == 0:
            # Tied in both — contributes to neither denominator term.
            ties_a += 1
            ties_b += 1
            continue
        if da == 0:
            ties_a += 1
            continue
        if db == 0:
            ties_b += 1
            continue
        if (da > 0) == (db > 0):
            concordant += 1
        else:
            discordant += 1

    n0 = n * (n - 1) / 2
    denom = ((n0 - ties_a) * (n0 - ties_b)) ** 0.5
    if denom == 0:
        # Every pair tied on one side: no ordering information to compare.
        return 1.0
    return (concordant - discordant) / denom


# ── the hosts under test ───────────────────────────────────────────────

def _load_host_dimensions(db_path: str) -> dict[str, list]:
    """Per-host dimension scores, from the latest scan of each host.

    Reuses the API's own scoping helpers rather than querying the DB directly,
    so this measures the same aggregation the console shows. If those helpers
    change, this analysis follows them instead of silently diverging.
    """
    from config_assessment.api.routers.posture import (
        _latest_results, assessed_dimensions,
    )
    from config_assessment.core.db.database import Database
    from config_assessment.core.engines.dimensions import (
        group_by_dimension, score_dimension,
    )

    db = Database(db_path)
    # host_id=None means "every host", the same scoping GET /posture uses with
    # no host filter. One scan per distinct input_path, so a config scanned
    # nightly does not outweigh one scanned once.
    results = _latest_results(db, None)

    by_host: dict[str, list] = {}
    for result in results:
        findings = list(getattr(result, "issues", []) or [])
        if not findings:
            continue

        # group_by_dimension buckets TEMPORAL SCORES, not finding objects —
        # score_dimension takes floats. Using the engine's own helper rather
        # than bucketing by hand also keeps the dimension_of() criterion in
        # one place.
        buckets = group_by_dimension(findings)
        # Which dimensions actually ran. An absent key here means "nothing was
        # bucketed there", which is NOT the same as clean, so `None` is passed
        # for dimensions that were never assessed — the distinction the whole
        # scoring model exists to preserve.
        assessed = assessed_dimensions([result])
        dimension_scores = [
            score_dimension(
                dim_id,
                buckets.get(dim_id, []) if dim_id in assessed else None,
            )
            for dim_id in set(buckets) | set(assessed)
        ]

        # Keyed by input_path, not target_name: _latest_results returns one
        # result per distinct configuration, and two configs of the same target
        # are two things to rank — collapsing them by target would silently
        # drop all but one.
        by_host[result.input_path] = dimension_scores
    return by_host


def _overall(dimension_scores: list, weights: dict[str, float]) -> float | None:
    """Recompute the overall under a given weight vector.

    Patches DIMENSION_WEIGHTS around the engine's own aggregate_posture call
    rather than reimplementing the weighted mean: the renormalisation over
    assessed dimensions and the missing-dimension policy are the subtle parts,
    and a copy of them here would be the thing that goes stale.
    """
    from config_assessment.core.engines import dimensions as dim_mod

    from dataclasses import replace

    original = dim_mod.DIMENSION_WEIGHTS
    try:
        dim_mod.DIMENSION_WEIGHTS = weights
        # score_dimension stamped each score with the OLD weight, and
        # aggregate_posture reads d.weight — NOT the module global — so
        # re-stamping is what actually applies the perturbation.
        #
        # dataclasses.replace, not a duck-typed `model_copy` guarded by
        # hasattr: DimensionScore is a stdlib dataclass, so that guard was
        # always false and every perturbation silently aggregated the
        # UNMODIFIED weights, producing a uniform delta of 0.000 that looked
        # like a robustness result. replace() raises on an unknown field
        # instead of quietly doing nothing.
        restamped = [replace(d, weight=weights.get(d.id)) for d in dimension_scores]
        return dim_mod.aggregate_posture(restamped).overall
    finally:
        dim_mod.DIMENSION_WEIGHTS = original


def _perturbations(base: dict[str, float], delta: float) -> Iterable[tuple[str, dict]]:
    """One perturbed weight vector per (dimension, direction).

    A one-at-a-time grid rather than a joint sample: it isolates WHICH
    dimension's weight the result is sensitive to, which is the actionable
    form of the answer. Scaling every weight at once is also reported, as the
    worst case.
    """
    for dim_id in base:
        for sign, name in ((1 + delta, "+"), (1 - delta, "-")):
            perturbed = dict(base)
            perturbed[dim_id] = base[dim_id] * sign
            yield f"{name}{int(delta * 100)}% {dim_id}", perturbed

    # A joint case, chosen to survive renormalisation.
    #
    # Any factor common to all ASSESSED dimensions cancels — so splitting the
    # six declared weights by rank is worthless when the assessed ones happen
    # to fall on the same side of the split (with configuration/permissions/
    # exposure assessed, ranking by weight moves all three up together and the
    # perturbation is exactly a no-op). Alternating instead guarantees the
    # split cuts across whichever subset is assessed, in either order.
    for offset, name in ((0, "alternating"), (1, "alternating'")):
        alternating = dict(base)
        for i, dim_id in enumerate(sorted(base)):
            up = (i + offset) % 2 == 0
            alternating[dim_id] = base[dim_id] * ((1 + delta) if up else (1 - delta))
        yield f"{name} ±{int(delta * 100)}%", alternating


# ── the analysis ───────────────────────────────────────────────────────

def run(db_path: str, delta: float) -> dict:
    from config_assessment.core.engines.dimensions import (
        DIMENSION_WEIGHTS, SCORING_MODEL_VERSION,
    )
    from config_assessment.core.engines import scoring

    hosts = _load_host_dimensions(db_path)
    if not hosts:
        return {"error": "no scans in the database — run an assessment first"}

    names = sorted(hosts)
    base_weights = dict(DIMENSION_WEIGHTS)

    baseline = [_overall(hosts[n], base_weights) for n in names]
    # A host whose dimensions are all unassessed has no overall; it cannot
    # participate in a ranking comparison, so it is excluded rather than
    # coerced to 0.0 — which is the false-assurance failure this model exists
    # to prevent.
    keep = [i for i, v in enumerate(baseline) if v is not None]
    names = [names[i] for i in keep]
    baseline = [baseline[i] for i in keep]

    if not names:
        return {"error": "no host has an assessed dimension"}

    # THE PRECONDITION THIS ANALYSIS NEEDS.
    #
    # aggregate_posture renormalises weights across the ASSESSED dimensions.
    # For a host with exactly one assessed dimension that renormalisation sends
    # its weight to 1.0 whatever it was, so the overall equals that dimension's
    # score identically — and every perturbation returns tau = 1.0, delta = 0.
    #
    # That is arithmetic, not evidence. Reporting it as "the ranking is robust
    # to the weights" would be a false claim: the weights were never applied.
    # So the multi-dimension hosts are counted and, if there are none, the
    # analysis refuses to produce a verdict.
    multi = [n for n in names if sum(
        1 for d in hosts[n] if d.assessed and d.score is not None) > 1]
    if not multi:
        return {
            "error": (
                "sensitivity is undefined on this database: all "
                f"{len(names)} hosts have exactly one assessed dimension, so "
                "weight renormalisation makes the overall identical to that "
                "dimension's score and every perturbation is a no-op. Scan "
                "hosts with a multi-dimension target (e.g. ubuntu2204) before "
                "reading a robustness result into tau = 1.0."
            ),
            "hosts": len(names),
            "hosts_multi_dimension": 0,
        }

    base_bands = [scoring.severity_label(v) for v in baseline]

    runs = []
    for label, weights in _perturbations(base_weights, delta):
        scores = [_overall(hosts[n], weights) for n in names]
        scores = [s if s is not None else 0.0 for s in scores]
        deltas = [abs(s - b) for s, b in zip(scores, baseline)]
        bands = [scoring.severity_label(s) for s in scores]
        flips = sum(1 for x, y in zip(bands, base_bands) if x != y)
        runs.append({
            "perturbation": label,
            "tau": round(kendall_tau_b(baseline, scores), 4),
            "max_score_delta": round(max(deltas), 4),
            "mean_score_delta": round(sum(deltas) / len(deltas), 4),
            "band_flips": flips,
        })

    taus = [r["tau"] for r in runs]
    return {
        "scoring_model_version": SCORING_MODEL_VERSION,
        "delta": delta,
        "hosts": len(names),
        # Only these hosts can move under a weight change; single-dimension
        # hosts are inert ballast that inflates tau's denominator with pairs
        # that could never have been discordant.
        "hosts_multi_dimension": len(multi),
        "host_names": names,
        "baseline_scores": baseline,
        "declared_weights": base_weights,
        "runs": runs,
        "summary": {
            "min_tau": round(min(taus), 4),
            "mean_tau": round(sum(taus) / len(taus), 4),
            "rankings_preserved": sum(1 for t in taus if t >= 0.9999),
            "total_perturbations": len(runs),
            "max_score_delta": round(max(r["max_score_delta"] for r in runs), 4),
            "total_band_flips": sum(r["band_flips"] for r in runs),
        },
    }


def report(data: dict) -> None:
    if "error" in data:
        print(f"  {data['error']}")
        return

    s = data["summary"]
    print("\n" + "=" * 68)
    print("  WEIGHT SENSITIVITY — CVM scoring model "
          f"v{data['scoring_model_version']}")
    print("=" * 68)
    print(f"  hosts: {data['hosts']} "
          f"({data['hosts_multi_dimension']} multi-dimension) · "
          f"perturbation: ±{int(data['delta'] * 100)}% one-at-a-time · "
          f"{s['total_perturbations']} runs")
    print()
    print("  PERTURBATION              TAU    MAX Δ   MEAN Δ  BAND FLIPS")
    print("  " + "-" * 60)
    for r in data["runs"]:
        print(f"  {r['perturbation']:<24} {r['tau']:>5.3f}  {r['max_score_delta']:>6.3f}  "
              f"{r['mean_score_delta']:>6.3f}  {r['band_flips']:>10}")

    print()
    print(f"  minimum tau across all perturbations : {s['min_tau']:.4f}")
    print(f"  rankings preserved exactly           : "
          f"{s['rankings_preserved']}/{s['total_perturbations']}")
    print(f"  largest score movement               : {s['max_score_delta']:.3f}")
    print(f"  severity-band flips                  : {s['total_band_flips']}")
    print()
    # The verdict is stated in words, because "tau = 1.0" answers a question
    # the reader did not ask; "the ranking does not depend on the weights" is
    # the claim the thesis actually needs to make.
    if s["min_tau"] >= 0.9999 and s["total_band_flips"] == 0:
        print("  VERDICT: the host ranking and every severity band are invariant")
        print("           under ±10% weight perturbation. The ordering an operator")
        print("           acts on does not depend on the declared weights.")
    elif s["min_tau"] >= 0.9:
        print("  VERDICT: ranking largely stable (tau >= 0.9), with some movement.")
        print("           Report the affected perturbations alongside the scores.")
    else:
        print("  VERDICT: the ranking is SENSITIVE to the declared weights.")
        print("           The weights must be justified, not merely stated.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--delta", type=float, default=0.10,
                    help="fractional perturbation (default 0.10 = ±10%%)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    data = run(args.db, args.delta)
    if args.json:
        json.dump(data, sys.stdout, indent=2)
        print()
    else:
        report(data)
    return 0 if "error" not in data else 1


if __name__ == "__main__":
    raise SystemExit(main())
