"""
config_assessment/api/routers/chains.py
---------------------------------------
GET /api/v1/chains — active attack chains, in the v2 shape (CONTRATO_API_V2.md §4).

`GET /scans/{id}/chains` already exists and returns the stored `AttackChain`
verbatim. It stays exactly as it is: the API contract is additive-only, and its
consumers depend on those field names. This route answers a different question —
"what chains are live across the current posture" — which is the one the console
actually asks, since the dashboard has no scan id in hand.

The scoping deliberately matches `/posture`: the same `_latest_results` set, the
same `active` filter. A chain shown here and the `chains.active_count` on the
posture page are then the same chains by construction, rather than two counts
that happen to agree today.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from config_assessment.api.chains import serialize_chain
from config_assessment.api.deps import get_db
from config_assessment.api.routers.posture import (
    _latest_results, assessed_dimensions)
from config_assessment.core.db.database import Database
from config_assessment.core.engines.dimensions import (
    DIMENSION_IDS, aggregate_posture, group_by_dimension, score_dimension)

router = APIRouter(prefix="/api/v1/chains", tags=["posture"])


@router.get("")
def list_chains(host_id: int | None = None,
                db: Database = Depends(get_db)) -> list[dict]:
    """Active attack chains across the latest assessment."""
    if host_id is not None and db.get_host(host_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found",
                              "message": "Host not found.", "detail": None}})

    results = _latest_results(db, host_id)
    findings = [i for r in results for i in r.issues]

    # Recomputed rather than passed in, because `exceeds_overall` is only
    # meaningful against the SAME number the posture page shows. Deriving it
    # from anything else would let a chain be flagged as outranking a score the
    # operator never saw.
    assessed = assessed_dimensions(results)
    buckets = group_by_dimension(findings)
    overall = aggregate_posture([
        score_dimension(dim_id,
                        buckets.get(dim_id, []) if dim_id in assessed else None)
        for dim_id in DIMENSION_IDS
    ]).overall

    chains = [c for r in results for c in r.chains if c.active]
    serialized = [serialize_chain(c, findings, overall_score=overall)
                  for c in chains]
    # Worst first, matching every other list in the console: the chain most
    # worth reading is the one at the top.
    return sorted(serialized, key=lambda c: c["score"], reverse=True)
