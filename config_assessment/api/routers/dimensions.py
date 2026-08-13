"""
config_assessment/api/routers/dimensions.py
-------------------------------------------
GET /api/v1/dimensions/{id} — one axis in detail (CONTRATO_API_V2.md §2).

Where `/posture` answers "how am I doing", this answers "why" for a single
dimension: the findings behind the score, their spread across severity bands,
and how the number moved.

An unassessed dimension is a 200, not a 404. The axis exists and the console
has a panel for it; what it lacks is data, and `status: "not_assessed"` with
`findings: []` and `score: null` says exactly that. A 404 would suggest the
dimension is not part of the model, which is a different and wrong claim.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from config_assessment.api.deps import get_db
from config_assessment.api.findings import (
    serialize_finding, severity_breakdown, target_labels)
from config_assessment.api.routers.posture import (
    IMPLEMENTED_DIMENSIONS, _latest_results)
from config_assessment.core.db.database import Database
from config_assessment.core.engines.dimensions import (
    DIMENSION_IDS, DIMENSION_LABELS, dimension_of, score_dimension)

router = APIRouter(prefix="/api/v1/dimensions", tags=["posture"])

# What each axis covers, for the panel header. Written for an operator
# deciding whether the dimension is the one they need, not as a restatement
# of the id.
DIMENSION_DESCRIPTIONS: dict[str, str] = {
    "configuration": "Directives in service configuration files, measured "
                     "against the benchmark for that technology.",
    "permissions": "File ownership, modes, SUID/SGID binaries and sudo policy.",
    "exposure": "Listening sockets and the interfaces they are bound to.",
    "secrets": "Credentials and private keys committed to configuration.",
    "patch": "Installed package versions against known fixed versions.",
    "hardening": "Kernel parameters and platform-level hardening settings.",
}


@router.get("/{dimension_id}")
def get_dimension(dimension_id: str, host_id: int | None = None,
                  db: Database = Depends(get_db)) -> dict:
    """One dimension, with the findings that produced its score."""
    if dimension_id not in DIMENSION_IDS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found",
                              "message": f"Unknown dimension '{dimension_id}'.",
                              "detail": None}})

    if host_id is not None and db.get_host(host_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found",
                              "message": "Host not found.", "detail": None}})

    results = _latest_results(db, host_id)
    assessed = bool(results) and dimension_id in IMPLEMENTED_DIMENSIONS

    mine = [f for r in results for f in r.issues
            if dimension_of(f) == dimension_id] if assessed else []
    scored = score_dimension(
        dimension_id, [f.temporal_score for f in mine] if assessed else None)

    labels = target_labels()
    chains_by_directive = _chains_by_directive(results)

    body = {
        "id": dimension_id,
        "label": DIMENSION_LABELS.get(dimension_id, dimension_id.title()),
        "status": scored.status,
        "score": scored.score,
        "severity": scored.severity,
        "description": DIMENSION_DESCRIPTIONS.get(dimension_id, ""),
        "assessed_at": max((r.timestamp for r in results), default=None)
                       if assessed else None,
        "severity_breakdown": severity_breakdown(mine),
        "findings": [
            serialize_finding(
                f,
                target_label=labels.get(f.target_name),
                in_chains=chains_by_directive.get(f.directive, []),
            )
            for f in sorted(mine, key=lambda f: f.temporal_score, reverse=True)
        ],
        "trend": _trend(db, dimension_id, host_id) if assessed else [],
    }
    if not scored.assessed:
        body["not_assessed_reason"] = (
            scored.not_assessed_reason if dimension_id not in IMPLEMENTED_DIMENSIONS
            else "No assessment has been run against this host yet.")
    return body


def _chains_by_directive(results) -> dict[str, list[str]]:
    """Which chains each directive participates in.

    A finding that is part of an attack chain is worth more attention than its
    individual score suggests, and this is what lets the console say so
    without the caller fetching every chain separately.
    """
    out: dict[str, list[str]] = {}
    for r in results:
        for chain in r.chains:
            if not chain.active:
                continue
            for directive in chain.misconfig_directives:
                ids = out.setdefault(directive, [])
                if chain.chain_id not in ids:
                    ids.append(chain.chain_id)
    return out


def _trend(db: Database, dimension_id: str, host_id: int | None) -> list[dict]:
    """How this dimension's score moved over past assessments.

    Reconstructed from stored scans rather than from a per-dimension history
    table, which does not exist yet. That has a real limit worth stating: only
    dimensions derived from persisted findings can be plotted, so a point is
    absent where an older scan predates the dimension model — absent, rather
    than drawn at zero.
    """
    rows = (db.get_scans_for_host(host_id, limit=30) if host_id is not None
            else db.list_scans(limit=30))

    points: list[dict] = []
    for row in reversed(rows):
        result = db.get_scan_result(row["id"])
        if result is None:
            continue
        scores = [f.temporal_score for f in result.issues
                  if dimension_of(f) == dimension_id]
        if not scores:
            continue
        points.append({"at": result.timestamp, "score": max(scores)})
    return points
