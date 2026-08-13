"""
tests/test_dimensions.py
------------------------
Tests for multidimensional scoring.

Most of these exist to defend ONE distinction: a dimension that was never
assessed must never be reportable as a dimension that was assessed and found
clean. v1 collapses both onto 0.0 — `scoring.aggregate([]) == 0.0` — and 0.0
renders green, so the collapse is not cosmetic: it makes the product claim
safety it never checked.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from config_assessment.core.engines.dimensions import (
    DIMENSION_IDS, DIMENSION_WEIGHTS, SCORING_MODEL_VERSION, aggregate_posture,
    compute_delta, dimension_of, group_by_dimension, score_dimension)


@dataclass
class FakeEvidence:
    kind: str


@dataclass
class FakeFinding:
    temporal_score: float
    dimension: str | None = None
    evidence: FakeEvidence | None = None


# ── the distinction ────────────────────────────────────────────────────

def test_never_assessed_has_no_score():
    d = score_dimension("secrets", None)
    assert d.status == "not_assessed"
    assert d.score is None, "None must never be coerced to 0.0"
    assert d.severity is None
    assert d.findings_count is None
    assert d.not_assessed_reason


def test_assessed_and_clean_scores_a_real_zero():
    d = score_dimension("permissions", [])
    assert d.status == "clean"
    assert d.score == 0.0, "a genuine zero — rules ran and found nothing"
    assert d.findings_count == 0


def test_clean_and_not_assessed_are_distinguishable():
    """The single most important assertion in this file."""
    clean = score_dimension("permissions", [])
    absent = score_dimension("permissions", None)
    assert clean.status != absent.status
    assert clean.score != absent.score
    assert (clean.score, absent.score) == (0.0, None)


def test_assessed_with_findings_takes_the_worst_case():
    d = score_dimension("configuration", [3.0, 7.5, 5.0])
    assert d.status == "assessed"
    assert d.score == 7.5, "worst case within a dimension, as in v1"
    assert d.findings_count == 3
    assert d.severity == "High"


def test_critical_findings_are_counted_separately():
    d = score_dimension("exposure", [9.5, 9.0, 8.9, 2.0])
    assert d.critical_count == 2, "only >= 9.0 counts as critical"
    assert d.findings_count == 4


def test_an_unassessed_dimension_reports_why():
    assert "not implemented" in score_dimension("patch", None).not_assessed_reason
    # An unknown dimension still gets a reason rather than a blank.
    assert score_dimension("configuration", None).not_assessed_reason


# ── roll-up ────────────────────────────────────────────────────────────

def test_posture_always_carries_every_dimension():
    """The UI decides how to show an unassessed axis; it is never told the
    axis does not exist."""
    posture = aggregate_posture([score_dimension("configuration", [5.0])])
    assert len(posture.dimensions) == len(DIMENSION_IDS)
    assert [d.id for d in posture.dimensions] == list(DIMENSION_IDS)
    assert posture.dimensions_assessed == 1


def test_unassessed_dimensions_are_excluded_not_zeroed():
    """Counting an unassessed dimension as 0.0 would reward not looking."""
    posture = aggregate_posture([
        score_dimension("configuration", [8.0]),
        score_dimension("permissions", None),
        score_dimension("exposure", None),
    ])
    assert posture.overall == 8.0, \
        "the two unassessed axes must not drag the mean toward zero"
    assert posture.dimensions_assessed == 1


def test_weights_are_renormalised_over_assessed_dimensions():
    posture = aggregate_posture([
        score_dimension("configuration", [10.0]),  # declared weight 0.28
        score_dimension("permissions", [0.0]),     # declared weight 0.24, clean
    ])
    # 10*0.28 / (0.28+0.24) = 5.4 — not 10*0.28 = 2.8, which is what dividing
    # by all six declared weights would give. The renormalisation is the point:
    # the four dimensions nobody assessed must not appear in the denominator.
    assert posture.overall == 5.4
    # Derived from the declared weights, not hard-coded alongside them, so a
    # weight change fails this test loudly instead of silently drifting.
    expected = 10.0 * DIMENSION_WEIGHTS["configuration"] / (
        DIMENSION_WEIGHTS["configuration"] + DIMENSION_WEIGHTS["permissions"])
    assert posture.overall == pytest.approx(round(expected, 1))


def test_a_clean_dimension_still_pulls_the_mean_down():
    """Clean is a real measurement and must count, unlike not_assessed."""
    with_clean = aggregate_posture([
        score_dimension("configuration", [10.0]),
        score_dimension("permissions", []),
    ]).overall
    without = aggregate_posture([
        score_dimension("configuration", [10.0]),
        score_dimension("permissions", None),
    ]).overall
    assert with_clean < without


def test_nothing_assessed_yields_no_number():
    posture = aggregate_posture([])
    assert posture.overall is None, "inventing 0.0 here is the bug, not the fix"
    assert posture.severity is None
    assert posture.dimensions_assessed == 0
    assert all(d.status == "not_assessed" for d in posture.dimensions)


def test_coverage_reports_how_much_was_looked_at():
    posture = aggregate_posture([
        score_dimension("configuration", [5.0]),
        score_dimension("permissions", []),
        score_dimension("exposure", [3.0]),
    ])
    assert posture.coverage == pytest.approx(3 / 6)


def test_coverage_distinguishes_equal_overalls():
    """An 8.0 over two dimensions is not the same claim as 8.0 over six."""
    narrow = aggregate_posture([score_dimension("configuration", [8.0])])
    wide = aggregate_posture([score_dimension(d, [8.0]) for d in DIMENSION_IDS])
    assert narrow.overall == wide.overall == 8.0
    assert narrow.coverage < wide.coverage


def test_the_model_declares_its_policy_and_version():
    posture = aggregate_posture([score_dimension("configuration", [5.0])])
    assert posture.missing_dimension_policy == "excluded"
    assert posture.scoring_model_version == SCORING_MODEL_VERSION


def test_declared_weights_cover_every_dimension():
    assert set(DIMENSION_WEIGHTS) == set(DIMENSION_IDS)
    assert sum(DIMENSION_WEIGHTS.values()) == pytest.approx(1.0)


# ── deltas ─────────────────────────────────────────────────────────────

def test_stable_is_zero_and_incomparable_is_none():
    """0.0 means compared-and-stable; None means no basis for comparison."""
    assert compute_delta(5.0, 5.0) == 0.0
    assert compute_delta(5.0, None) is None
    assert compute_delta(None, 5.0) is None


def test_delta_signs_the_direction():
    assert compute_delta(7.0, 5.0) == 2.0
    assert compute_delta(3.0, 5.0) == -2.0


# ── evidence → dimension ───────────────────────────────────────────────

@pytest.mark.parametrize("kind,expected", [
    ("config_file", "configuration"),
    ("file_metadata", "permissions"),
    ("listening_socket", "exposure"),
    ("package", "patch"),
])
def test_evidence_kind_picks_the_dimension(kind, expected):
    f = FakeFinding(temporal_score=5.0, evidence=FakeEvidence(kind=kind))
    assert dimension_of(f) == expected


def test_an_explicit_dimension_wins_over_the_evidence_kind():
    f = FakeFinding(temporal_score=5.0, dimension="exposure",
                    evidence=FakeEvidence(kind="config_file"))
    assert dimension_of(f) == "exposure"


def test_v1_findings_fall_back_to_configuration():
    """Every v1 rule was read out of a config file, so that is the honest
    default for findings that predate the dimension field."""
    assert dimension_of(FakeFinding(temporal_score=5.0)) == "configuration"


def test_an_unknown_declared_dimension_is_not_trusted():
    f = FakeFinding(temporal_score=5.0, dimension="invented")
    assert dimension_of(f) == "configuration"


def test_grouping_buckets_by_dimension():
    findings = [
        FakeFinding(7.5, evidence=FakeEvidence("config_file")),
        FakeFinding(3.0, evidence=FakeEvidence("config_file")),
        FakeFinding(9.1, evidence=FakeEvidence("file_metadata")),
    ]
    assert group_by_dimension(findings) == {
        "configuration": [7.5, 3.0], "permissions": [9.1]}


def test_grouping_omits_dimensions_with_no_findings():
    """Absent is not clean — it is the caller that knows whether rules ran."""
    buckets = group_by_dimension([FakeFinding(5.0)])
    assert set(buckets) == {"configuration"}
    assert "permissions" not in buckets


def test_grouping_end_to_end_keeps_the_two_states_apart():
    """The realistic caller shape: rules ran for two dimensions, one of which
    came back clean, and a third never ran at all."""
    buckets = group_by_dimension([
        FakeFinding(7.5, evidence=FakeEvidence("config_file")),
    ])
    ran = {"configuration", "permissions"}

    posture = aggregate_posture([
        score_dimension(d, buckets.get(d, [])) for d in ran
    ])
    by_id = {d.id: d for d in posture.dimensions}
    assert by_id["configuration"].status == "assessed"
    assert by_id["permissions"].status == "clean"
    assert by_id["exposure"].status == "not_assessed"
    assert by_id["exposure"].score is None
