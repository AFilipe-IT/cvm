"""
config_assessment/api/chains.py
-------------------------------
The shared attack-chain shape (CONTRATO_API_V2.md §4).

The persisted `AttackChain` is a v1 record: it names the directives that
triggered it and carries an amplified score, but it says nothing about which
findings those directives became, which dimensions they cross, or whether the
chain outranks the host's own posture. Those are exactly the questions the
console asks, so they are answered here, once, rather than in each caller.

WHY A SECOND SHAPE INSTEAD OF A WIDER FIRST ONE
    `GET /scans/{id}/chains` returns `list[AttackChain]` — the stored model
    verbatim — and the API contract is additive-only: existing shapes are never
    mutated. Renaming `chain_id` to `id` there would break every current
    consumer, so the v2 shape lives alongside it and the v1 route is untouched.

WHAT THIS DOES NOT DO
    It does not change what a chain scores. Chains are reported, not folded
    into the overall posture (see the `exceeds_overall` note below) — this
    module reshapes an existing judgement, it does not make a new one.
"""

from __future__ import annotations

from config_assessment.core.engines import scoring
from config_assessment.core.engines.dimensions import dimension_of

# What a directive contributes to the chain. The stored model records only
# ORDER, so the first step is where the attacker starts and the last is what
# they reach; anything between is a step along the way. Naming them is honest
# about that: these are positions in a sequence, not a claim about technique.
_ROLE_ENTRY = "entry"
_ROLE_PIVOT = "pivot"
_ROLE_IMPACT = "impact"


def _role(index: int, total: int) -> str:
    if total == 1:
        # A one-directive chain is not really a sequence. Calling it "entry"
        # would imply a next step that does not exist.
        return _ROLE_IMPACT
    if index == 0:
        return _ROLE_ENTRY
    if index == total - 1:
        return _ROLE_IMPACT
    return _ROLE_PIVOT


def _title(chain) -> str:
    """A readable name for the chain.

    `chain_id` is a slug the engine assigned (`server-info-to-tls-downgrade`),
    which is already a sentence in disguise. Un-slugging it beats inventing
    prose the engine never wrote, and beats showing the raw slug in a heading.
    """
    return chain.chain_id.replace("-", " ").replace("_", " ").strip().capitalize()


def serialize_chain(chain, findings, *, overall_score: float | None = None) -> dict:
    """One persisted attack chain, in the contract's chain shape.

    `findings` is the scan's misconfigurations, used to resolve each triggering
    directive to the finding it became. A directive with no matching finding is
    dropped from `steps` rather than rendered as a placeholder: the chain fired
    on evidence, and a step the console cannot link back to a finding would be
    an assertion with nothing behind it.
    """
    by_directive = {f.directive: f for f in findings
                    if f.target_name == chain.target_name}
    # Fall back across targets for a cross-target chain, where the triggering
    # directive belongs to a different service than the chain's own target.
    for f in findings:
        by_directive.setdefault(f.directive, f)

    matched = [(d, by_directive[d]) for d in chain.misconfig_directives
               if d in by_directive]

    steps = []
    for i, (directive, finding) in enumerate(matched):
        score = getattr(finding, "temporal_score", 0.0)
        steps.append({
            "order": i + 1,
            "finding_id": finding.id,
            "dimension": dimension_of(finding),
            "identifier": directive,
            "score": score,
            "role": _role(i, len(matched)),
        })

    score = chain.amplified_score
    return {
        "id": chain.chain_id,
        "title": _title(chain),
        "score": score,
        "severity": scoring.severity_label(score),
        "active": chain.active,
        "amplification": chain.amplification,
        # Chains do not raise the overall score — the posture is the worst
        # individual finding, and amplification is reported beside it rather
        # than folded into it. This flag is how the console says "this chain
        # scores above the number at the top of the page", which is precisely
        # the case where reporting-only matters to the reader.
        "exceeds_overall": (overall_score is not None and score > overall_score),
        # A chain that crosses dimensions is a different argument than one
        # confined to a single axis: it means no single collector would have
        # shown the whole path. Derived from the resolved steps, so it cannot
        # disagree with what the console renders.
        "cross_dimension": len({s["dimension"] for s in steps}) > 1,
        "narrative": chain.justification or None,
        "steps": steps,
    }
