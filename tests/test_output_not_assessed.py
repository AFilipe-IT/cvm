"""Zero findings has two causes that mean the opposite of each other.

Everything was checked and passed, or nothing was ever checked. Both reach the
same branch in `_output.py` with an empty `result.issues`, and until this was
fixed both printed `0.0 / 10`, `NONE`, and a green "No issues detected" — the
strongest all-clear the tool can give, handed to a system nothing had looked at.

The failure is silent by construction: no exception, no warning, a plausible
number. It was found by scanning a synthetic Ubuntu root whose `/etc/shadow` was
mode 0644, against a database holding no `ubuntu2204` rules. The scan reported a
clean system. The signal separating the two cases was already in the manifest —
`rules_for_target` — it just was not consulted.

These tests pin the distinction at the rendering layer, which is the last place
it can be lost before a human reads it.
"""

from datetime import datetime

import pytest

from cli import _output
from config_assessment.core.models import ScanResult, SystemProfile


def _plain(captured: str) -> str:
    """Rendered output without ANSI, so assertions read the text a user sees."""
    return _output._strip_ansi(captured)


class TestScorePanel:
    """The box is the first thing read and the most quoted out of context."""

    def test_an_unassessed_target_shows_na_not_a_zero(self):
        lines = _plain("\n".join(_output._risk_box_lines(0.0, "None", assessed=False)))

        assert "N/A" in lines
        assert "NOT ASSESSED" in lines
        # 0.0 is the specific wrong answer: it is not merely uninformative, it
        # is the best possible score, claimed for an unmeasured system.
        assert "0.0" not in lines
        assert "NONE" not in lines

    def test_an_assessed_clean_target_still_shows_zero(self):
        """The inverse error, and just as damaging.

        A real 0.0 is an earned result. Rendering it as N/A would destroy the
        distinction from the other side — every clean system would look
        unmeasured, and the operator would learn to ignore the warning.
        """
        lines = _plain("\n".join(_output._risk_box_lines(0.0, "None", assessed=True)))

        assert "0.0 / 10" in lines
        assert "NONE" in lines
        assert "N/A" not in lines
        assert "NOT ASSESSED" not in lines

    def test_a_scored_target_is_untouched(self):
        lines = _plain("\n".join(_output._risk_box_lines(7.1, "High", assessed=True)))

        assert "7.1 / 10" in lines
        assert "HIGH" in lines

    def test_the_unassessed_panel_keeps_the_scored_panel_geometry(self):
        """The caller prints this side by side with the summary block.

        A box of a different height or width would break the alignment on
        exactly the scan that most needs to be read carefully.
        """
        scored = _output._risk_box_lines(5.0, "Medium", assessed=True)
        unassessed = _output._risk_box_lines(0.0, "None", assessed=False)

        assert len(scored) == len(unassessed)
        widths = {len(_output._strip_ansi(line)) for line in scored + unassessed}
        assert len(widths) == 1, f"ragged box widths: {widths}"

    def test_the_meter_track_differs_from_a_scored_one(self):
        """The graphic has to disclaim itself too, not only the number.

        A scored meter draws an unfilled remainder in `░`. Reusing that same
        track for an unassessed target makes the panel look like a measured
        score of nearly zero — the number says N/A, the bar says "almost
        nothing wrong", and the bar is what gets read first. The inert track
        uses its own glyph so the two are never confusable.
        """
        unassessed = _plain("\n".join(_output._risk_box_lines(0.0, "None", assessed=False)))
        scored = _plain("\n".join(_output._risk_box_lines(7.0, "High", assessed=True)))

        assert "█" not in unassessed and "░" not in unassessed
        # Guards the assertion above: were the scored meter to stop using these
        # glyphs, the check would pass while testing nothing.
        assert "█" in scored and "░" in scored


def _result(manifest):
    """A zero-findings `ScanResult` carrying `manifest`.

    The real model rather than a stub: the branch under test reads a handful of
    its fields, and a hand-rolled fake would keep passing if the model grew a
    field the renderer started depending on.
    """
    result = ScanResult(
        target_name=manifest.get("target", "ubuntu2204"),
        input_path="/srv/fixture",
        input_hash="0" * 64,
        profile=SystemProfile(av="N", au="N"),
        timestamp=datetime(2026, 8, 14, 12, 0, 0),
    )
    result.manifest = manifest
    return result


class TestVerdictLine:
    """The sentence under the box, which is what gets believed."""

    def test_an_empty_knowledge_base_is_reported_as_not_assessed(self, capsys):
        _output._print_result(_result({"rules_for_target": 0,
                                       "target": "ubuntu2204"}))
        out = _plain(capsys.readouterr().out)

        assert "Not assessed" in out
        assert "This is NOT a" in out and "clean result" in out
        assert "No issues detected" not in out
        # The operator needs the way out, not just the diagnosis.
        assert "plugin fetch ubuntu2204" in out

    def test_a_populated_knowledge_base_with_no_findings_is_clean(self, capsys):
        _output._print_result(_result({"rules_for_target": 18,
                                       "target": "ubuntu"}))
        out = _plain(capsys.readouterr().out)

        assert "No issues detected" in out
        assert "Not assessed" not in out

    def test_a_manifest_without_the_key_is_treated_as_assessed(self, capsys):
        """Absence of the key is not evidence of an empty knowledge base.

        Older scans and any caller that builds a partial manifest have no
        `rules_for_target`. Reading a missing key as zero would relabel every
        one of them "not assessed", which is the louder and more damaging
        error: a warning that fires on healthy scans stops being read.
        """
        _output._print_result(_result({"target": "nginx"}))
        out = _plain(capsys.readouterr().out)

        assert "No issues detected" in out
        assert "Not assessed" not in out


@pytest.mark.parametrize("rules,expect_na", [(0, True), (1, False), (18, False)])
def test_only_an_exact_zero_suppresses_the_score(rules, expect_na, capsys):
    """One rule is a thin knowledge base; zero is a different claim entirely.

    A single rule that found nothing is a real, if narrow, assessment. Only the
    empty set means no finding was possible.
    """
    _output._print_result(_result({"rules_for_target": rules, "target": "t"}))
    out = _plain(capsys.readouterr().out)

    assert ("N/A" in out) is expect_na
    assert ("No issues detected" in out) is not expect_na
