"""
config_assessment/core/engines/dimensions.py
--------------------------------------------
Multidimensional scoring (v2).

THE DISTINCTION THIS MODULE EXISTS TO ENFORCE
    A dimension that was never assessed must never look like a dimension that
    was assessed and found clean. The v1 engine cannot express that: its
    `scoring.aggregate([])` returns 0.0, so "no findings" and "no assessment"
    collapse onto the same number — and 0.0 renders green.

    That collapse makes the product lie. A system where one dimension was
    examined cannot present the same indicator as one where six were examined
    and nothing was found. So a dimension here carries a `status`, and a score
    of `None` that is never coerced to zero:

        assessed     — rules ran, findings exist       score is a number
        clean        — rules ran, nothing found        score is 0.0
        not_assessed — no rules ran                    score is None

WEIGHTS AND THE MISSING-DIMENSION POLICY
    The overall indicator is a weighted mean over ASSESSED dimensions only,
    with the weights renormalised across those (`missing_dimension_policy:
    "excluded"`). The alternative — treating an unassessed dimension as zero —
    would reward not looking, which is the opposite of what a posture tool
    should do.

    Renormalising has its own honest cost: an overall computed over two
    dimensions is not comparable with one computed over six. `coverage`
    reports that ratio so the caller can say so rather than hide it.

WHY THE OVERALL IS A WEIGHTED MEAN AND NOT THE WORST CASE
    v1 scores a config path by its worst finding, which is right there: one
    fatal directive is fatal regardless of how many benign ones surround it.
    Across dimensions that reasoning breaks — a host with one critical
    exposure finding and clean permissions is genuinely in better shape than
    one critical in both, and a max() cannot tell those apart. The per-
    dimension score stays worst-case; only the roll-up across dimensions is a
    mean. `driver` keeps the worst individual finding visible so the
    actionability v1 guaranteed is not lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal

from config_assessment.core.engines import scoring

DimensionStatus = Literal["assessed", "clean", "not_assessed"]

# The six axes the console renders. Order is the contract's order and is what
# the radar chart plots clockwise from the top, so it is not incidental.
DIMENSION_IDS: tuple[str, ...] = (
    "configuration", "secrets", "exposure", "hardening", "patch", "permissions",
)

# Labels are the console's, and come from the API contract rather than from
# this module's taste — the two must not drift.
DIMENSION_LABELS: dict[str, str] = {
    "configuration": "Configuration",
    "secrets": "Secrets",
    "exposure": "Network Exposure",
    "hardening": "OS Hardening",
    "patch": "Patch Intelligence",
    "permissions": "Identity & Permissions",
}

# Declared weights (`weights_source: "declared"`). They are deliberately not
# uniform: a wrong directive in a config file is the dimension the whole
# knowledge base is built on and carries the most evidence, while patch and
# hardening are not implemented in this build at all.
#
# These are a policy input, not a measurement. They are versioned with the
# scoring model so a score can always be recomputed from a stated position,
# and changing them changes SCORING_MODEL_VERSION.
# The three implemented dimensions are weighted so that, once renormalised
# over just those three, they land on the 0.35 / 0.30 / 0.35 the API contract
# shows — the contract's figures ARE the renormalised ones, and a reader
# comparing the two documents must not find them disagreeing.
DIMENSION_WEIGHTS: dict[str, float] = {
    "configuration": 0.28,
    "permissions": 0.24,
    "exposure": 0.28,
    "secrets": 0.10,
    "patch": 0.06,
    "hardening": 0.04,
}

SCORING_MODEL_VERSION = "2.0"

# Reasons carried to the UI when a dimension has no assessment. Keyed by
# dimension so the console can say WHY rather than showing a blank.
NOT_ASSESSED_REASONS: dict[str, str] = {
    "secrets": "Secret detection is not implemented in this build.",
    "patch": "Patch intelligence is not implemented in this build.",
    "hardening": "Platform hardening checks are not implemented in this build.",
    "permissions": "No permissions collector has run against this system.",
    "exposure": "No network exposure collector has run against this system.",
}
_DEFAULT_REASON = "No rules were evaluated for this dimension."


@dataclass
class DimensionScore:
    """One axis of the assessment.

    `score` is None exactly when `status == "not_assessed"`. Callers must not
    coerce it to 0.0 — that is the bug this whole module exists to prevent.
    """

    id: str
    label: str
    status: DimensionStatus
    score: float | None = None
    severity: str | None = None
    weight: float | None = None
    findings_count: int | None = None
    critical_count: int | None = None
    delta: float | None = None
    not_assessed_reason: str | None = None

    @property
    def assessed(self) -> bool:
        """True when rules actually ran — including when they found nothing."""
        return self.status != "not_assessed"


@dataclass
class PostureScore:
    """The host-level roll-up across every dimension."""

    overall: float | None
    severity: str | None
    dimensions: list[DimensionScore] = field(default_factory=list)
    dimensions_total: int = len(DIMENSION_IDS)
    dimensions_assessed: int = 0
    scoring_model_version: str = SCORING_MODEL_VERSION
    missing_dimension_policy: str = "excluded"

    @property
    def coverage(self) -> float:
        """Fraction of dimensions actually assessed, 0.0–1.0.

        The honesty companion to `overall`: an 8.0 over two dimensions and an
        8.0 over six are not the same claim, and this is what distinguishes
        them.
        """
        return self.dimensions_assessed / self.dimensions_total


def score_dimension(
    dimension_id: str,
    scores: Iterable[float] | None,
    *,
    delta: float | None = None,
    critical_threshold: float = 9.0,
) -> DimensionScore:
    """Score one dimension from the temporal scores of its findings.

    `scores=None` means the dimension was never assessed. An empty iterable
    means it WAS assessed and came back clean — the two are different inputs
    producing deliberately different outputs, which is the whole point.
    """
    label = DIMENSION_LABELS.get(dimension_id, dimension_id.title())

    if scores is None:
        return DimensionScore(
            id=dimension_id, label=label, status="not_assessed",
            not_assessed_reason=NOT_ASSESSED_REASONS.get(
                dimension_id, _DEFAULT_REASON),
        )

    values = list(scores)
    weight = DIMENSION_WEIGHTS.get(dimension_id)

    if not values:
        # Assessed and clean. The score is a real 0.0 here, not a stand-in for
        # missing data, so it is safe to render green.
        return DimensionScore(
            id=dimension_id, label=label, status="clean", score=0.0,
            severity=scoring.severity_label(0.0), weight=weight,
            findings_count=0, critical_count=0, delta=delta,
        )

    # Worst case within a dimension, matching v1: one fatal finding is fatal
    # however many benign ones sit beside it.
    score = scoring.aggregate(values)
    return DimensionScore(
        id=dimension_id, label=label, status="assessed", score=score,
        severity=scoring.severity_label(score), weight=weight,
        findings_count=len(values),
        critical_count=sum(1 for v in values if v >= critical_threshold),
        delta=delta,
    )


def aggregate_posture(dimensions: list[DimensionScore]) -> PostureScore:
    """Combine per-dimension scores into one host indicator.

    A weighted mean over assessed dimensions, weights renormalised across
    them. Every declared dimension is present in the output whatever its
    status — the UI decides how to show an unassessed axis, but it is never
    told the axis does not exist.
    """
    by_id = {d.id: d for d in dimensions}
    ordered = [
        by_id.get(dim_id) or score_dimension(dim_id, None)
        for dim_id in DIMENSION_IDS
    ]

    assessed = [d for d in ordered if d.assessed and d.score is not None]
    if not assessed:
        # Nothing was assessed: there is no number to report, and inventing a
        # 0.0 here would be the exact failure this module prevents.
        return PostureScore(overall=None, severity=None, dimensions=ordered,
                            dimensions_assessed=0)

    total_weight = sum(d.weight or 0.0 for d in assessed)
    if total_weight > 0:
        overall = sum((d.score or 0.0) * (d.weight or 0.0)
                      for d in assessed) / total_weight
    else:
        # No declared weights (an unknown dimension id): fall back to an equal
        # split rather than dividing by zero.
        overall = sum(d.score or 0.0 for d in assessed) / len(assessed)

    overall = round(overall, 1)
    return PostureScore(
        overall=overall,
        severity=scoring.severity_label(overall),
        dimensions=ordered,
        dimensions_assessed=len(assessed),
    )


def dimension_of(finding: object) -> str:
    """Which dimension a finding belongs to.

    The criterion is the NATURE OF THE EVIDENCE, not the topic of the rule.
    A finding recovered by reading a directive out of a config file is
    `configuration` whether it concerns TLS, authentication or logging; one
    recovered from an inode is `permissions`; one from a listening socket is
    `exposure`. That is a different axis from the v1 categories, which
    classify a rule's subject matter — both are useful and neither replaces
    the other.

    Findings produced before the dimension field existed carry no marker, so
    they fall back to `configuration`: every v1 rule was, by construction,
    read out of a configuration file.

    The evidence is a DICT (`Directive.evidence`), not an object, and on a
    `Misconfiguration` it hangs off `source_directive` — the finding is the
    rule that matched, the directive is the observation that matched it. Both
    are read here, because a caller holding either one is asking the same
    question.
    """
    dimension = getattr(finding, "dimension", None)
    if dimension in DIMENSION_IDS:
        return dimension

    evidence = getattr(finding, "evidence", None)
    if not evidence:
        directive = getattr(finding, "source_directive", None)
        evidence = getattr(directive, "evidence", None)

    kind = evidence.get("kind") if isinstance(evidence, dict) else None
    return _EVIDENCE_DIMENSION.get(kind, "configuration")


def group_by_dimension(findings: Iterable[object]) -> dict[str, list[float]]:
    """Bucket findings' temporal scores by dimension.

    Only dimensions that actually received findings appear. A caller must not
    read an absent key as "clean" — absent means nothing was bucketed there,
    and it is the caller that knows whether rules ran. That is precisely the
    distinction `score_dimension(None)` vs `score_dimension([])` encodes.
    """
    buckets: dict[str, list[float]] = {}
    for f in findings:
        score = getattr(f, "temporal_score", None)
        if score is None:
            continue
        buckets.setdefault(dimension_of(f), []).append(score)
    return buckets


# Evidence kind → dimension. Mirrors the `Evidence` union in the API contract
# (config_file | file_metadata | listening_socket | package).
_EVIDENCE_DIMENSION: dict[str | None, str] = {
    "config_file": "configuration",
    "file_metadata": "permissions",
    "listening_socket": "exposure",
    "package": "patch",
}


def compute_delta(current: float | None, previous: float | None) -> float | None:
    """Change since the previous assessment.

    `None` means "not comparable" — a first assessment, or one where the
    dimension was not assessed on either side. `0.0` means "compared, and
    stable". The contract is explicit that the UI must not conflate them, so
    neither does this.
    """
    if current is None or previous is None:
        return None
    return round(current - previous, 1)
