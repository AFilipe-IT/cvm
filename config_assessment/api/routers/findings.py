"""
config_assessment/api/routers/findings.py
-----------------------------------------
GET /api/v1/findings — the filterable list (CONTRATO_API_V2.md §7).

The console's triage view. Filtering happens here rather than in the browser
because the estate is large — the reference database holds 6323 findings — and
shipping all of them so the client can hide most is both slow and a lie about
what `total` means under pagination.

`total` counts everything matching the filters, not the page. A caller
paginating through 31 results must see 31 at every offset, or the pager cannot
be drawn.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from config_assessment.api.deps import get_db
from config_assessment.api.findings import serialize_finding, target_labels
from config_assessment.api.routers.dimensions import _chains_by_directive
from config_assessment.api.routers.posture import _latest_results
from config_assessment.core.db.database import Database
from config_assessment.core.engines import scoring
from config_assessment.core.engines.dimensions import DIMENSION_IDS, dimension_of

router = APIRouter(prefix="/api/v1/findings", tags=["posture"])

_SEVERITIES = {"Critical", "High", "Medium", "Low", "None"}
_STATUSES = {"open", "resolved", "suppressed"}


def _invalid(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": {"code": "invalid_parameter", "message": message,
                          "detail": None}})


@router.get("")
def list_findings(
    dimension: str | None = None,
    target: str | None = None,
    severity: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    has_cve: bool | None = None,
    in_chain: bool | None = None,
    q: str | None = None,
    host_id: int | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Database = Depends(get_db),
) -> dict:
    """Findings across the latest assessment of each configuration."""
    # An unknown filter value is rejected rather than silently matching
    # nothing: an empty list would read as "you are clean", which is the
    # opposite of "you asked for something that does not exist".
    if dimension is not None and dimension not in DIMENSION_IDS:
        raise _invalid(f"Unknown dimension '{dimension}'.")
    if severity is not None and severity not in _SEVERITIES:
        raise _invalid(f"Unknown severity '{severity}'. "
                       f"Expected one of: {', '.join(sorted(_SEVERITIES))}.")
    if status_filter is not None and status_filter not in _STATUSES:
        raise _invalid(f"Unknown status '{status_filter}'.")
    if host_id is not None and db.get_host(host_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found",
                              "message": "Host not found.", "detail": None}})

    results = _latest_results(db, host_id)
    chains_by_directive = _chains_by_directive(results)
    labels = target_labels()

    matched = [
        f for r in results for f in r.issues
        if _matches(f, dimension=dimension, target=target, severity=severity,
                    status_filter=status_filter, has_cve=has_cve,
                    in_chain=in_chain, q=q,
                    chains_by_directive=chains_by_directive)
    ]
    matched.sort(key=lambda f: f.temporal_score, reverse=True)

    page = matched[offset:offset + limit]
    return {
        "total": len(matched),
        "limit": limit,
        "offset": offset,
        "findings": [
            serialize_finding(f, target_label=labels.get(f.target_name),
                              in_chains=chains_by_directive.get(f.directive, []))
            for f in page
        ],
    }


def _matches(f, *, dimension, target, severity, status_filter, has_cve,
             in_chain, q, chains_by_directive) -> bool:
    if dimension is not None and dimension_of(f) != dimension:
        return False
    if target is not None and f.target_name != target:
        return False
    if severity is not None and scoring.severity_label(f.temporal_score) != severity:
        return False
    # Everything persisted is open: resolution is inferred from a finding's
    # absence in a later scan, and suppressed findings are dropped at scan
    # time, so neither ever reaches this list.
    if status_filter is not None and status_filter != "open":
        return False
    if has_cve is not None and bool(f.cves) is not has_cve:
        return False
    if in_chain is not None:
        if bool(chains_by_directive.get(f.directive)) is not in_chain:
            return False
    if q:
        needle = q.lower()
        haystack = " ".join(str(x) for x in (
            f.directive, f.bad_value, f.good_value, f.target_name,
            getattr(f, "justification", ""), getattr(f, "recommendation", ""),
        ) if x)
        if needle not in haystack.lower():
            return False
    return True
