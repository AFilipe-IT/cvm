"""
config_assessment/api/scoring_explain.py
----------------------------------------
Why a finding scores what it scores (CONTRATO_API_V2.md §3).

A finding arrives at the console as a number and a severity band. That is
enough to rank it and not nearly enough to defend it: an operator asked to
justify remediation work, or a reader asked to trust the methodology, needs to
see WHICH metric produced the number. `PermitRootLogin` scoring 8.5 is an
assertion; scoring 8.5 because it is reachable over the network (AV:N, 1.000),
needs no credentials (Au:N, 0.704) and fully compromises integrity (I:C, 0.660)
is an argument.

This module turns the six stored CCSS metrics plus the two temporal ones into
that argument: each metric with its human name, the NISTIR 7502 §3.2 weight it
contributes, and the two formulas with the actual numbers substituted in.

DERIVED, NEVER RE-IMPLEMENTED
    The weights and formulas are read from `core/engines/scoring.py`, which is
    the single source of truth for the mathematics. A second copy here would
    eventually disagree with the engine, and a scoring explanation that
    contradicts the score is worse than no explanation — it would discredit a
    number that is in fact correct.
"""

from __future__ import annotations

import json

from config_assessment.core.engines import scoring

# Human names for the stored codes. The database holds "N"/"P"/"C" because
# that is the CCSS vector notation; nobody reading a console should have to
# carry that table in their head.
_AV_NAMES = {"L": "Local", "A": "Adjacent network", "N": "Network"}
_AU_NAMES = {"M": "Multiple", "S": "Single", "N": "None"}
_AC_NAMES = {"H": "High", "M": "Medium", "L": "Low"}
_CIA_NAMES = {"N": "None", "P": "Partial", "C": "Complete"}
_GEL_NAMES = {"N": "None", "L": "Low", "M": "Medium", "H": "High",
              "ND": "Not defined"}
_GRL_NAMES = {"U": "Unavailable", "W": "Workaround", "H": "Official fix",
              "ND": "Not defined"}

# What each metric asks. Phrased as the question the metric answers, so the
# reader can check the assigned value against their own system rather than
# take it on faith.
_QUESTIONS = {
    "AV": "From where can this be exploited?",
    "Au": "How many times must an attacker authenticate first?",
    "AC": "How much has to go right for the attack to work?",
    "C": "How much of the system's confidentiality is lost?",
    "I": "How much of the system's integrity is lost?",
    "A": "How much of the system's availability is lost?",
    "GEL": "How readily available is the exploitation technique?",
    "GRL": "How available is an official remediation?",
}


def _metric(code: str, value: str, names: dict, weights: dict,
            justification: str | None = None) -> dict:
    """One row of the explanation.

    `weight` is None for a value the engine does not recognise. That is a data
    problem worth showing rather than hiding behind a plausible default: a
    finding stored with a bad metric is exactly what an auditor needs to see.

    `justification` is the build pipeline's written reason for THIS value —
    why AV is N and not L for this particular rule. The weight explains what
    the value costs; only this explains why the value was chosen, which is the
    part a reader has to accept on evidence rather than arithmetic.
    """
    return {
        "code": code,
        "value": value,
        "label": names.get(value, value),
        "weight": weights.get(value),
        "question": _QUESTIONS[code],
        "justification": justification or None,
    }


def _metric_justifications(m) -> dict:
    """The per-metric reasons recorded at build time, keyed by lowercase code.

    They live inside the `narrative` JSON column rather than in columns of
    their own, and only the LLM pipeline writes them — hand-curated and
    pre-pipeline rules carry `"{}"`. A malformed blob returns nothing instead
    of raising: one bad row must not take down the finding's whole detail
    view, and the arithmetic below stands on its own regardless.
    """
    raw = getattr(m, "narrative", None)
    if not raw:
        return {}
    if isinstance(raw, dict):          # already decoded upstream
        parsed = raw
    else:
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    if not isinstance(parsed, dict):
        return {}
    found = parsed.get("metric_justifications")
    if not isinstance(found, dict):
        return {}
    return {str(k).lower(): v for k, v in found.items() if isinstance(v, str)}


def explain_score(m) -> dict | None:
    """The scoring rationale for one persisted misconfiguration.

    Returns None when the finding carries no vector at all — a rule stored
    before the metrics were recorded. The console renders the score without
    the breakdown in that case, which is honest; inventing a vector to fill
    the panel would attribute an assessment nobody made.
    """
    av = getattr(m, "av", None)
    ac = getattr(m, "ac", None)
    au = getattr(m, "au", None)
    c = getattr(m, "c", None)
    i = getattr(m, "i", None)
    a = getattr(m, "a", None)
    if not all((av, ac, au, c, i, a)):
        return None

    gel = getattr(m, "gel", None) or "ND"
    grl = getattr(m, "grl", None) or "ND"

    j = _metric_justifications(m)
    exploitability = [
        _metric("AV", av, _AV_NAMES, scoring._AV, j.get("av")),
        _metric("Au", au, _AU_NAMES, scoring._AU, j.get("au")),
        _metric("AC", ac, _AC_NAMES, scoring._AC, j.get("ac")),
    ]
    impact = [
        _metric("C", c, _CIA_NAMES, scoring._CIA, j.get("c")),
        _metric("I", i, _CIA_NAMES, scoring._CIA, j.get("i")),
        _metric("A", a, _CIA_NAMES, scoring._CIA, j.get("a")),
    ]
    temporal = [
        _metric("GEL", gel, _GEL_NAMES, scoring._GEL, j.get("gel")),
        _metric("GRL", grl, _GRL_NAMES, scoring._GRL, j.get("grl")),
    ]

    # Recomputed from the engine rather than read off the row, so the panel
    # shows the arithmetic that the stored score should satisfy. When the two
    # disagree the row is stale, and `matches_stored` says so instead of
    # quietly showing whichever number happens to be at hand.
    base = scoring.base_score(av, au, ac, c, i, a)
    temporal_value = scoring.temporal_score(base, gel, grl)
    stored = getattr(m, "temporal_score", None)

    f_impact = 10.41 * (1 - (1 - scoring._CIA[c]) * (1 - scoring._CIA[i])
                        * (1 - scoring._CIA[a]))
    f_exploit = 20 * scoring._AV[av] * scoring._AU[au] * scoring._AC[ac]

    return {
        "vector": f"AV:{av} AC:{ac} Au:{au} C:{c} I:{i} A:{a}",
        "exploitability": exploitability,
        "impact": impact,
        "temporal": temporal,
        "base_score": base,
        "temporal_score": temporal_value,
        # Both formulas with the numbers substituted, so the reader can check
        # the arithmetic by hand — the property that makes the score auditable
        # rather than merely reported.
        "steps": [
            {
                "label": "Impact sub-score",
                "formula": "10.41 × (1 − (1−C) × (1−I) × (1−A))",
                "substituted": (
                    f"10.41 × (1 − {1 - scoring._CIA[c]:.3f} × "
                    f"{1 - scoring._CIA[i]:.3f} × {1 - scoring._CIA[a]:.3f})"),
                "value": round(f_impact, 2),
            },
            {
                "label": "Exploitability sub-score",
                "formula": "20 × AV × Au × AC",
                "substituted": (f"20 × {scoring._AV[av]:.3f} × "
                                f"{scoring._AU[au]:.3f} × {scoring._AC[ac]:.3f}"),
                "value": round(f_exploit, 2),
            },
            {
                "label": "Base score",
                "formula": "((0.6 × impact) + (0.4 × exploitability) − 1.5) × 1.176",
                "substituted": (f"((0.6 × {f_impact:.2f}) + "
                                f"(0.4 × {f_exploit:.2f}) − 1.5) × 1.176"),
                "value": base,
            },
            {
                "label": "Temporal score",
                "formula": "base × GEL × GRL",
                "substituted": (f"{base} × {scoring._GEL[gel]:.3f} × "
                                f"{scoring._GRL[grl]:.3f}"),
                "value": temporal_value,
            },
        ],
        "matches_stored": stored is None or abs(temporal_value - stored) < 0.05,
        # Lets the console distinguish "this rule records no reasons" from
        # "the reasons exist but this view drops them" — the two look identical
        # once every row's justification is null.
        "has_justifications": bool(j),
        "reference": "NISTIR 7502 §3.2",
    }
