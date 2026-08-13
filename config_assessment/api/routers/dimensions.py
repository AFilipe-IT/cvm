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
    IMPLEMENTABLE_DIMENSIONS, _latest_results, assessed_dimensions)
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

# What a dimension WOULD report, had it been assessed.
#
# This exists so an unassessed axis can say something concrete instead of
# rendering an empty panel. An empty panel reads as "nothing to report here",
# which is the false-assurance failure the whole not_assessed distinction is
# meant to prevent: the operator must be able to see what they are missing, not
# merely that a number is absent.
#
# The entries describe checks the knowledge base already carries, so they are a
# statement about coverage not yet exercised — not a roadmap.
DIMENSION_WOULD_MEASURE: dict[str, list[str]] = {
    "configuration": [
        "Directives that deviate from the benchmark for each detected service.",
        "Settings left at an insecure default because they were never stated.",
        "Directives absent from the knowledge base, flagged rather than passed.",
    ],
    "permissions": [
        "World-writable files and directories outside the expected set.",
        "SUID and SGID binaries beyond the distribution baseline.",
        "Ownership and mode of credential files such as private keys.",
        "Sudo policy granting unrestricted or password-less escalation.",
    ],
    "exposure": [
        "Every listening socket and the interface it is bound to.",
        "Datastores reachable beyond loopback, whatever port they listen on.",
        "The process owning each socket, so a service can be named not guessed.",
    ],
    "secrets": [
        "Passwords and API tokens written literally into configuration.",
        "Private keys stored alongside the configuration that references them.",
        "Credentials left in environment files readable by other users.",
    ],
    "patch": [
        "Installed package versions against known fixed versions.",
        "CVEs applying to the running versions of the assessed services.",
    ],
    "hardening": [
        "Kernel parameters governing network and memory protections.",
        "Mandatory access control state (AppArmor or SELinux).",
        "Boot and module-loading restrictions.",
    ],
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
    # Whether this dimension was examined is a property of what the scans DID
    # (which targets ran), not of what the build could do — scanning an
    # nginx.conf examines no inode and no socket.
    assessed = dimension_id in assessed_dimensions(results)

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
        "would_measure": DIMENSION_WOULD_MEASURE.get(dimension_id, []),
        # Taken from the scored result rather than recounted here, so this
        # endpoint and /posture cannot drift on what "critical" means. They are
        # null when unassessed for the same reason the score is: "0 findings"
        # is a result, and nobody looked.
        "weight": scored.weight,
        "findings_count": scored.findings_count,
        "critical_count": scored.critical_count,
        "delta": scored.delta,
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
        # "Not implemented" is only honest for a dimension no target can do.
        # When the build CAN assess it and simply has not here, say that
        # instead — otherwise an operator goes hunting for a missing feature.
        body["not_assessed_reason"] = (
            scored.not_assessed_reason
            if dimension_id not in IMPLEMENTABLE_DIMENSIONS
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
