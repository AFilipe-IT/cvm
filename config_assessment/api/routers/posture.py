"""
config_assessment/api/routers/posture.py
----------------------------------------
GET /api/v1/posture — the multidimensional view the v2 console opens on.

Distinct from `GET /api/v1/hosts`, which is v1's cross-target rollup and keeps
its exact behaviour: the difference is that this endpoint reports per-dimension
status, and therefore reports what was NOT assessed as well as what was. See
CONTRATO_API_V2.md §1.

The endpoint is deliberately thin — it maps persisted findings onto dimensions
and serialises the result. All the scoring judgement lives in
core/engines/dimensions.py, so the CLI and the API cannot disagree about what a
score means.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from config_assessment.api.deps import get_db
from config_assessment.core.db.database import Database
from config_assessment.core.engines.dimensions import (
    DIMENSION_IDS, SCORING_MODEL_VERSION, aggregate_posture, compute_delta,
    group_by_dimension, score_dimension)

router = APIRouter(prefix="/api/v1/posture", tags=["posture"])

# Dimensions this build actually evaluates. The rest are reported
# `not_assessed` — the contract is explicit that they must still appear.
#
# `permissions` and `exposure` are listed here only once their collectors land
# (Fase C); until then a build that claimed to assess them would be reporting
# clean for something it never looked at, which is the failure this whole
# model exists to prevent.
IMPLEMENTED_DIMENSIONS: frozenset[str] = frozenset({"configuration"})


def _serialize_dimension(d, assessed_at: str | None,
                         reason: str | None = None) -> dict:
    """`reason` overrides the engine's default explanation.

    The engine can only say why a dimension has no implementation; it cannot
    know that no scan ran at all. Telling an operator that configuration
    assessment "is not implemented" when the real answer is "you have not
    scanned anything yet" would send them looking for a missing feature.
    """
    return {
        "id": d.id,
        "label": d.label,
        "status": d.status,
        "score": d.score,
        "severity": d.severity,
        "weight": d.weight,
        "findings_count": d.findings_count,
        "critical_count": d.critical_count,
        "delta": d.delta,
        "assessed_at": assessed_at if d.assessed else None,
        **({"not_assessed_reason": reason or d.not_assessed_reason}
           if (reason or d.not_assessed_reason) else {}),
    }


@router.get("")
def get_posture(host_id: int | None = None, db: Database = Depends(get_db)) -> dict:
    """The overall posture, broken down by dimension.

    With `host_id`, scopes to one inventoried host; without it, reports across
    the latest scan of every assessed configuration.
    """
    if host_id is not None and db.get_host(host_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Host not found")

    results = _latest_results(db, host_id)
    findings = [i for r in results for i in r.issues]
    chains = [c for r in results for c in r.chains if c.active]
    buckets = group_by_dimension(findings)

    # A dimension counts as assessed only when a scan actually ran. With no
    # results at all there is nothing to be clean about: passing `[]` here
    # would report an unexamined host as examined-and-clean, which is the
    # precise failure the dimension model exists to prevent. `None` — never
    # looked — is the honest answer, so `assessed` gates the whole set.
    assessed = bool(results)

    previous = _previous_scores(db, host_id)
    dimensions = [
        score_dimension(
            dim_id,
            buckets.get(dim_id, [])
            if assessed and dim_id in IMPLEMENTED_DIMENSIONS else None,
            delta=compute_delta(
                max(buckets[dim_id]) if buckets.get(dim_id) else None,
                previous.get(dim_id)),
        )
        for dim_id in DIMENSION_IDS
    ]
    posture = aggregate_posture(dimensions)

    assessed_at = max((r.timestamp for r in results), default=None)
    driver = _driver(findings)
    highest_chain = max((c.amplified_score for c in chains), default=None)

    return {
        "overall": {
            "score": posture.overall,
            "severity": posture.severity,
            # No stored history of the composite score yet, so there is no
            # honest term of comparison. null means "not comparable", which is
            # exactly what this is — not 0.0, which would claim stability.
            "delta": None,
            "driver": driver,
        },
        "coverage": {
            "dimensions_total": posture.dimensions_total,
            "dimensions_assessed": posture.dimensions_assessed,
            "percent": round(posture.coverage * 100),
        },
        "dimensions": [
            _serialize_dimension(
                d, assessed_at,
                None if assessed or d.id not in IMPLEMENTED_DIMENSIONS
                else "No assessment has been run against this host yet.")
            for d in posture.dimensions
        ],
        "chains": {
            "active_count": len(chains),
            "highest_score": highest_chain,
            # Chains still do not feed the overall score — the v1
            # actionability decision stands. Flagging when one outranks it is
            # how the console surfaces that without silently folding it in.
            "exceeds_overall": bool(
                highest_chain is not None and posture.overall is not None
                and highest_chain > posture.overall),
        },
        "totals": {
            "targets_assessed": len({r.target_name for r in results}),
            "findings_open": len(findings),
            "critical_findings": sum(1 for f in findings
                                     if f.temporal_score >= 9.0),
        },
        "scoring_model": {
            "version": SCORING_MODEL_VERSION,
            "aggregation": "weighted",
            "missing_dimension_policy": posture.missing_dimension_policy,
            "weights_source": "declared",
        },
        "assessed_at": assessed_at,
    }


def _latest_results(db: Database, host_id: int | None) -> list:
    """The most recent scan of each distinct configuration.

    One scan per input_path, so a file scanned nightly does not outweigh one
    scanned once — the same rule `GET /hosts` already applies.
    """
    rows = (db.get_scans_for_host(host_id, limit=500) if host_id is not None
            else db.list_scans(limit=500))
    latest: dict[str, dict] = {}
    for row in rows:
        latest.setdefault(row["input_path"], row)
    results = [db.get_scan_result(r["id"]) for r in latest.values()]
    return [r for r in results if r is not None]


def _previous_scores(db: Database, host_id: int | None) -> dict[str, float]:
    """Per-dimension scores of the assessment before the current one.

    Empty for now: nothing persists a per-dimension history yet, so every
    delta comes back null. That is the honest answer — a fabricated baseline
    would make the console show movement that never happened.
    """
    return {}


def _driver(findings: list) -> dict | None:
    """What produced the number, so the operator can act on it.

    v1's guarantee was that a score always traces to a concrete directive.
    Averaging across dimensions would lose that, so the worst individual
    finding travels alongside the mean.
    """
    if not findings:
        return None
    worst = max(findings, key=lambda f: f.temporal_score)
    from config_assessment.core.engines.dimensions import dimension_of
    return {
        "kind": "finding",
        "dimension": dimension_of(worst),
        "label": f"{worst.directive} = {worst.bad_value}",
        "score": worst.temporal_score,
    }
