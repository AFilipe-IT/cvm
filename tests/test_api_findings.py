"""
tests/test_api_findings.py
--------------------------
Tests for GET /api/v1/dimensions/{id} and GET /api/v1/findings, plus the
shared finding serialiser they and /posture all use.

Two properties get most of the attention here. First, that an unassessed
dimension answers 200 with empty data rather than 404 — the axis exists, only
its data is missing, and the console has a panel either way. Second, that what
the knowledge base does not know is reported as null instead of as a
convincing-looking blank.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest
pytest.importorskip("fastapi", reason="API tests need the [api] extra "
                    "(pip install -e '.[dev]')")

from fastapi.testclient import TestClient  # noqa: E402

from config_assessment.api.findings import serialize_finding, severity_breakdown
from config_assessment.api.scoring_explain import explain_score
from config_assessment.core import runtime
from config_assessment.core.db.database import Database
from config_assessment.core.engines.scoring import base_score, temporal_score
from config_assessment.core.models import (
    AttackChain, Directive, Misconfiguration, TargetMetadata)


@pytest.fixture(autouse=True)
def clear_registry():
    original = list(runtime._REGISTRY)
    runtime._REGISTRY.clear()
    yield
    runtime._REGISTRY.clear()
    runtime._REGISTRY.extend(original)


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)

    database = Database(path)
    database.upsert_target(TargetMetadata(
        name="dummy", display_name="Dummy Test Target", version="1.0",
        benchmark_source="findings test fixture",
    ))
    bs = base_score("N", "N", "L", "P", "P", "P")
    ts = temporal_score(bs, "M", "H")
    database.upsert_misconfiguration(Misconfiguration(
        target_name="dummy", directive="DangerousOption", bad_value="on",
        good_value="off", av="N", au="N", ac="L", c="P", i="P", a="P",
        base_score=bs, temporal_score=ts, gel="M", grl="H",
        cves=["CVE-2023-00001"], cce_id="CCE-TEST-001", cis_section="1.1",
        justification="DangerousOption=on exposes the system.",
        recommendation="Set DangerousOption=off in the config.",
    ))
    database.upsert_attack_chain(AttackChain(
        chain_id="test-chain", target_name="dummy",
        misconfig_directives=["DangerousOption", "Listen"],
        amplification=1.5, justification="Combined attack path.",
    ))
    database.close()
    yield path
    os.unlink(path)


@pytest.fixture
def dummy_config_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".dummy", delete=False) as f:
        f.write("Listen=0.0.0.0:80\nDangerousOption=on\n")
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture
def client(db_path):
    from config_assessment.plugins.dummy import DummyPlugin
    runtime.register_plugin(DummyPlugin())
    from config_assessment.api.app import create_app
    with TestClient(create_app(db_path=db_path)) as c:
        yield c


@pytest.fixture
def scanned(client, dummy_config_file):
    r = client.post("/api/v1/scans", json={"input_path": dummy_config_file})
    assert r.status_code in (200, 201), r.text
    return client


# ── the serialiser ─────────────────────────────────────────────────────

class TestFindingSerialization:
    def _misconfig(self, **kw):
        defaults = dict(
            target_name="dummy", directive="ServerTokens", bad_value="Full",
            good_value="Prod", ac="L", c="P", i="N", a="N", temporal_score=8.5)
        return Misconfiguration(**{**defaults, **kw})

    def test_the_contract_fields_are_all_present(self):
        body = serialize_finding(self._misconfig())
        assert set(body) >= {
            "id", "dimension", "target", "target_label", "identifier",
            "observed_value", "expected_value", "score", "severity", "title",
            "impact", "recommendation", "evidence", "cves", "references",
            "in_chains", "first_seen", "status"}

    def test_a_rule_without_a_narrative_reports_null_not_filler(self):
        """No LLM narrative means no impact statement. An empty string would
        render as a present-but-blank field; null says there is none."""
        body = serialize_finding(self._misconfig(narrative="{}"))
        assert body["impact"] is None

    def test_a_broken_narrative_does_not_cost_the_finding(self):
        """Enrichment is optional; the finding itself must still be reportable
        when the JSON attached to it is malformed."""
        body = serialize_finding(self._misconfig(narrative="{not json"))
        assert body["identifier"] == "ServerTokens"
        assert body["impact"] is None

    def test_the_narrative_supplies_title_and_impact(self):
        body = serialize_finding(self._misconfig(narrative=(
            '{"description": "Version disclosed.", '
            '"potential_impact": ["Enables targeted attacks", "Speeds up scanning"]}'
        )))
        assert body["title"] == "Version disclosed."
        assert "Enables targeted attacks." in body["impact"]
        assert "Speeds up scanning." in body["impact"]

    def test_the_justification_backs_the_title_when_there_is_no_narrative(self):
        body = serialize_finding(self._misconfig(justification="Leaks version."))
        assert body["title"] == "Leaks version."

    def test_a_rule_never_observed_carries_no_evidence(self):
        """A knowledge-base rule describes what WOULD be a finding. Attaching
        evidence would credit an observation to a file nobody read."""
        assert serialize_finding(self._misconfig())["evidence"] is None

    def test_an_observed_finding_carries_file_and_line(self):
        body = serialize_finding(self._misconfig(source_directive=Directive(
            name="ServerTokens", value="Full",
            source_file="/etc/apache2/apache2.conf", line_number=142)))
        ev = body["evidence"]
        assert ev["kind"] == "config_file"
        assert ev["location"] == "/etc/apache2/apache2.conf"
        assert ev["line"] == 142
        assert "ServerTokens" in ev["snippet"]

    def test_a_file_mode_finding_carries_metadata_not_a_line(self):
        """A mode is a property of the inode. Reporting a line number and a
        snippet for it would attribute the finding to a line of config text
        that does not exist."""
        body = serialize_finding(self._misconfig(source_directive=Directive(
            name="file_mode:/etc/shadow", value="0644",
            source_file="/etc/shadow",
            evidence={"kind": "file_metadata", "location": "/etc/shadow",
                      "mode": "0644", "owner": "root", "group": "shadow"})))
        ev = body["evidence"]
        assert ev["kind"] == "file_metadata"
        assert ev["location"] == "/etc/shadow"
        assert ev["mode"] == "0644"
        assert ev["owner"] == "root"
        assert ev["group"] == "shadow"
        assert "line" not in ev and "snippet" not in ev

    def test_a_socket_finding_carries_the_process(self):
        body = serialize_finding(self._misconfig(source_directive=Directive(
            name="listen:tcp/0.0.0.0:6379", value="redis-server",
            evidence={"kind": "listening_socket",
                      "location": "tcp/0.0.0.0:6379",
                      "process": "redis-server", "pid": 812})))
        ev = body["evidence"]
        assert ev["kind"] == "listening_socket"
        assert ev["location"] == "tcp/0.0.0.0:6379"
        assert ev["process"] == "redis-server"
        assert ev["pid"] == 812

    def test_an_unresolved_process_stays_null_rather_than_guessed(self):
        body = serialize_finding(self._misconfig(source_directive=Directive(
            name="listen:tcp/0.0.0.0:6379", value="unknown",
            evidence={"kind": "listening_socket",
                      "location": "tcp/0.0.0.0:6379",
                      "process": None, "pid": None})))
        assert body["evidence"]["process"] is None

    def test_a_v1_directive_without_evidence_keeps_the_config_file_shape(self):
        """The v1 path must be untouched: no collector fills `evidence`, and
        those findings still report file, line and snippet."""
        body = serialize_finding(self._misconfig(source_directive=Directive(
            name="ServerTokens", value="Full",
            source_file="/etc/apache2/apache2.conf", line_number=142)))
        assert body["evidence"]["kind"] == "config_file"
        assert body["evidence"]["line"] == 142

    def test_benchmark_references_are_carried(self):
        body = serialize_finding(self._misconfig(cis_section="2.5",
                                                 cce_id="CCE-12345-6"))
        labels = [r["label"] for r in body["references"]]
        assert "CIS §2.5" in labels
        assert "CCE-12345-6" in labels

    def test_severity_breakdown_reports_empty_bands_as_zero(self):
        """A fixed set of bars needs every band present — a missing key would
        force the console to infer that absent means zero."""
        counts = severity_breakdown([self._misconfig(temporal_score=8.5)])
        assert set(counts) == {"Critical", "High", "Medium", "Low", "None"}
        assert counts["High"] == 1
        assert counts["Critical"] == 0


# ── GET /dimensions/{id} ───────────────────────────────────────────────

class TestDimensionDetail:
    def test_an_assessed_dimension_returns_its_findings(self, scanned):
        body = scanned.get("/api/v1/dimensions/configuration").json()
        assert body["status"] == "assessed"
        assert body["score"] > 0
        assert body["findings"], "the findings behind the score must be listed"
        assert body["description"], "the panel header explains what the axis covers"

    def test_findings_are_ordered_worst_first(self, scanned):
        scores = [f["score"]
                  for f in scanned.get("/api/v1/dimensions/configuration").json()["findings"]]
        assert scores == sorted(scores, reverse=True)

    def test_the_severity_breakdown_sums_to_the_finding_count(self, scanned):
        body = scanned.get("/api/v1/dimensions/configuration").json()
        assert sum(body["severity_breakdown"].values()) == len(body["findings"])

    def test_chain_membership_travels_with_the_finding(self, scanned):
        """A finding inside a chain deserves more attention than its own score
        suggests; the console must not have to fetch every chain to know."""
        findings = scanned.get("/api/v1/dimensions/configuration").json()["findings"]
        chained = [f for f in findings if f["in_chains"]]
        assert chained, "the fixture's chain covers DangerousOption"
        assert "test-chain" in chained[0]["in_chains"]

    def test_an_unassessed_dimension_is_200_with_empty_data_not_404(self, scanned):
        """The axis exists — only its data is missing. A 404 would claim the
        dimension is not part of the model at all."""
        r = scanned.get("/api/v1/dimensions/exposure")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "not_assessed"
        assert body["score"] is None
        assert body["findings"] == []
        assert body["trend"] == []
        assert body["not_assessed_reason"]

    def test_an_unassessed_dimension_still_reports_its_bands(self, scanned):
        counts = scanned.get("/api/v1/dimensions/exposure").json()["severity_breakdown"]
        assert set(counts) == {"Critical", "High", "Medium", "Low", "None"}
        assert sum(counts.values()) == 0

    def test_an_unknown_dimension_is_a_404(self, client):
        r = client.get("/api/v1/dimensions/telepathy")
        assert r.status_code == 404
        assert r.json()["detail"]["error"]["code"] == "not_found"

    def test_the_trend_is_reconstructed_from_past_scans(self, client,
                                                        dummy_config_file):
        for _ in range(2):
            client.post("/api/v1/scans", json={"input_path": dummy_config_file})
        trend = client.get("/api/v1/dimensions/configuration").json()["trend"]
        assert len(trend) >= 2
        assert all("at" in p and "score" in p for p in trend)

    def test_an_unknown_host_is_a_404(self, client):
        assert client.get("/api/v1/dimensions/configuration?host_id=999"
                          ).status_code == 404


# ── GET /findings ──────────────────────────────────────────────────────

class TestFindingsList:
    def test_it_lists_findings_with_pagination_metadata(self, scanned):
        body = scanned.get("/api/v1/findings").json()
        assert body["total"] >= 1
        assert body["limit"] == 50
        assert body["offset"] == 0
        assert len(body["findings"]) == body["total"]

    def test_total_counts_matches_not_the_page(self, scanned):
        """A pager cannot be drawn if total shrinks as you page through it."""
        full = scanned.get("/api/v1/findings").json()["total"]
        paged = scanned.get("/api/v1/findings?limit=1&offset=0").json()
        assert paged["total"] == full
        assert len(paged["findings"]) == 1

    def test_offset_past_the_end_is_empty_but_still_reports_total(self, scanned):
        body = scanned.get("/api/v1/findings?offset=10000").json()
        assert body["findings"] == []
        assert body["total"] >= 1

    def test_filtering_by_dimension(self, scanned):
        assert scanned.get("/api/v1/findings?dimension=configuration").json()["total"] >= 1
        assert scanned.get("/api/v1/findings?dimension=exposure").json()["total"] == 0

    def test_filtering_by_target(self, scanned):
        assert scanned.get("/api/v1/findings?target=dummy").json()["total"] >= 1
        assert scanned.get("/api/v1/findings?target=nginx").json()["total"] == 0

    def test_filtering_by_severity(self, scanned):
        total = scanned.get("/api/v1/findings").json()["total"]
        bands = ["Critical", "High", "Medium", "Low", "None"]
        summed = sum(scanned.get(f"/api/v1/findings?severity={b}").json()["total"]
                     for b in bands)
        assert summed == total, "every finding lands in exactly one band"

    def test_filtering_by_cve_presence(self, scanned):
        with_cve = scanned.get("/api/v1/findings?has_cve=true").json()
        assert with_cve["total"] >= 1
        assert all(f["cves"] for f in with_cve["findings"])
        without = scanned.get("/api/v1/findings?has_cve=false").json()
        assert all(not f["cves"] for f in without["findings"])

    def test_filtering_by_chain_membership(self, scanned):
        chained = scanned.get("/api/v1/findings?in_chain=true").json()
        assert chained["total"] >= 1
        assert all(f["in_chains"] for f in chained["findings"])

    def test_free_text_search_matches_the_directive(self, scanned):
        assert scanned.get("/api/v1/findings?q=DangerousOption").json()["total"] >= 1
        assert scanned.get("/api/v1/findings?q=zzzznomatch").json()["total"] == 0

    def test_free_text_search_is_case_insensitive(self, scanned):
        lower = scanned.get("/api/v1/findings?q=dangerousoption").json()["total"]
        exact = scanned.get("/api/v1/findings?q=DangerousOption").json()["total"]
        assert lower == exact >= 1

    def test_results_are_ordered_worst_first(self, scanned):
        scores = [f["score"] for f in scanned.get("/api/v1/findings").json()["findings"]]
        assert scores == sorted(scores, reverse=True)

    def test_an_unknown_filter_value_is_rejected_not_silently_empty(self, client):
        """An empty list would read as 'you are clean'. The honest answer to a
        filter that cannot match anything is that the filter is wrong."""
        for qs in ("dimension=telepathy", "severity=Huge", "status=pending"):
            r = client.get(f"/api/v1/findings?{qs}")
            assert r.status_code == 400, qs
            assert r.json()["detail"]["error"]["code"] == "invalid_parameter"

    def test_limit_is_bounded(self, client):
        assert client.get("/api/v1/findings?limit=0").status_code == 422
        assert client.get("/api/v1/findings?limit=99999").status_code == 422

    def test_an_unknown_host_is_a_404(self, client):
        assert client.get("/api/v1/findings?host_id=999").status_code == 404


# ── scan-scoped listing ────────────────────────────────────────────────

class TestScanScopedFindings:
    """`?scan_id=` narrows the list to one assessment.

    The estate-wide list is right for triage and wrong immediately after a
    scan: someone who has just assessed one file is asking what THIS run
    found, and the reference database holds 6323 findings to bury it under.
    """

    def test_a_scan_id_restricts_the_list_to_that_assessment(
            self, scanned, dummy_config_file):
        everything = scanned.get("/api/v1/findings").json()["total"]

        # A second scan of the same input, so the estate holds more than the
        # one run being asked about.
        r = scanned.post("/api/v1/scans", json={"input_path": dummy_config_file})
        scan_id = r.json()["scan_id"]

        scoped = scanned.get(f"/api/v1/findings?scan_id={scan_id}").json()
        assert scoped["total"] >= 1
        assert scoped["total"] <= everything

    def test_the_scoped_findings_all_belong_to_that_scan(
            self, scanned, dummy_config_file):
        r = scanned.post("/api/v1/scans", json={"input_path": dummy_config_file})
        scan_id = r.json()["scan_id"]

        detail = scanned.get(f"/api/v1/scans/{scan_id}").json()
        expected = {i["directive"] for i in detail.get("issues", [])}

        scoped = scanned.get(f"/api/v1/findings?scan_id={scan_id}").json()
        assert {f["identifier"] for f in scoped["findings"]} == expected

    def test_an_unknown_scan_is_a_404_not_an_empty_list(self, client):
        """Same reasoning as the unknown-filter case, and the same reasoning
        the renderer applies to an empty knowledge base: 'this assessment found
        nothing' and 'there is no such assessment' must not look identical."""
        r = client.get("/api/v1/findings?scan_id=00000000-dead-beef-0000-000000000000")
        assert r.status_code == 404
        assert r.json()["detail"]["error"]["code"] == "not_found"

    def test_other_filters_still_apply_within_a_scan(
            self, scanned, dummy_config_file):
        r = scanned.post("/api/v1/scans", json={"input_path": dummy_config_file})
        scan_id = r.json()["scan_id"]
        both = scanned.get(
            f"/api/v1/findings?scan_id={scan_id}&q=zzzznomatch").json()
        assert both["total"] == 0


# ── scoring rationale ──────────────────────────────────────────────────

class TestScoringExplanation:
    """A score with no derivation is an assertion; with one it is an argument.

    The console cannot justify remediation work — nor can a reader audit the
    methodology — from a bare number, so every finding carries the metrics that
    produced it and the arithmetic that combined them.
    """

    def _misconfig(self, **kw):
        defaults = dict(
            target_name="dummy", directive="PermitRootLogin", bad_value="yes",
            good_value="no", av="N", au="N", ac="L", c="P", i="C", a="N",
            gel="H", grl="H")
        m = Misconfiguration(**{**defaults, **kw})
        m.base_score = base_score(m.av, m.au, m.ac, m.c, m.i, m.a)
        m.temporal_score = temporal_score(m.base_score, m.gel, m.grl)
        return m

    def test_every_metric_is_named_and_weighted(self):
        s = serialize_finding(self._misconfig())["scoring"]
        codes = {m["code"] for group in ("exploitability", "impact", "temporal")
                 for m in s[group]}
        assert codes == {"AV", "Au", "AC", "C", "I", "A", "GEL", "GRL"}
        for group in ("exploitability", "impact", "temporal"):
            for m in s[group]:
                assert m["label"], m["code"]
                assert m["weight"] is not None, m["code"]
                assert m["question"].endswith("?")

    def test_the_weights_are_the_nistir_values_not_a_second_copy(self):
        """Read from the scoring engine, so a change there cannot leave the
        explanation quietly disagreeing with the score it explains."""
        s = serialize_finding(self._misconfig())["scoring"]
        weights = {m["code"]: m["weight"] for m in s["exploitability"]}
        assert weights["AV"] == 1.000    # Network
        assert weights["Au"] == 0.704    # None
        assert weights["AC"] == 0.710    # Low

    def test_the_arithmetic_reproduces_the_stored_score(self):
        m = self._misconfig()
        s = serialize_finding(m)["scoring"]
        assert s["temporal_score"] == m.temporal_score
        assert s["matches_stored"] is True
        # The last step's value IS the temporal score: the panel's bottom line
        # and the headline number must not be able to disagree.
        assert s["steps"][-1]["value"] == m.temporal_score

    def test_the_vector_matches_the_stored_metrics(self):
        s = serialize_finding(self._misconfig())["scoring"]
        assert s["vector"] == "AV:N AC:L Au:N C:P I:C A:N"

    def test_a_finding_without_a_vector_claims_no_derivation(self):
        """A row stored before the metrics were recorded. The score still
        renders; inventing a vector would attribute an assessment nobody made.

        Built as a bare object rather than a `Misconfiguration`: the model
        requires the vector fields, so this state cannot be constructed through
        it — which is itself why the guard stays cheap. It protects against rows
        that predate the model, not against anything the model can produce now.
        """
        class _Legacy:
            id = "legacy-1"
            target_name = "dummy"
            directive = "Legacy"
            bad_value = "on"
            good_value = "off"
            temporal_score = 5.0
            av = ac = au = c = i = a = None

        assert explain_score(_Legacy()) is None

    def test_the_justification_is_exposed_separately_from_the_title(self):
        """`title` falls back to the justification when no LLM narrative
        exists, so the console needs the field itself to tell a heading from
        the benchmark's stated reason."""
        m = self._misconfig(justification="Root login over SSH is reachable.")
        body = serialize_finding(m)
        assert body["justification"] == "Root login over SSH is reachable."


class TestPerMetricJustifications:
    """WHY each metric holds its value, not just what the value costs.

    The weight explains the arithmetic; only this explains the assignment. The
    build pipeline writes these into the `narrative` JSON column, where the v1
    console read them and the v2 one did not — the score was auditable as
    arithmetic but not as judgement.
    """

    def _with_narrative(self, narrative):
        m = Misconfiguration(
            target_name="dummy", directive="ServerTokens", bad_value="Full",
            good_value="Prod", av="N", au="N", ac="L", c="P", i="N", a="N",
            gel="M", grl="H")
        m.base_score = base_score(m.av, m.au, m.ac, m.c, m.i, m.a)
        m.temporal_score = temporal_score(m.base_score, m.gel, m.grl)
        m.narrative = narrative
        return m

    def _by_code(self, s):
        return {m["code"]: m for group in ("exploitability", "impact", "temporal")
                for m in s[group]}

    def test_each_recorded_reason_reaches_its_own_metric(self):
        m = self._with_narrative(json.dumps({"metric_justifications": {
            "ac": "AC=L: a single unauthenticated HTTP request suffices.",
            "c": "C=P: discloses the Apache version and module list.",
        }}))
        s = serialize_finding(m)["scoring"]
        metrics = self._by_code(s)
        assert s["has_justifications"] is True
        assert metrics["AC"]["justification"].startswith("AC=L:")
        assert metrics["C"]["justification"].startswith("C=P:")

    def test_metrics_the_pipeline_did_not_write_stay_null(self):
        """Partial coverage is the common case — the console must be able to
        say "no reason recorded" for one metric while showing text for another,
        rather than borrowing a neighbour's sentence."""
        m = self._with_narrative(json.dumps({"metric_justifications": {
            "ac": "AC=L: trivially reachable."}}))
        metrics = self._by_code(serialize_finding(m)["scoring"])
        assert metrics["AC"]["justification"] is not None
        assert metrics["AV"]["justification"] is None
        assert metrics["I"]["justification"] is None

    @pytest.mark.parametrize("narrative", [
        None, "", "{}", "{ not json at all", "[]",
        json.dumps({"description": "no metric block here"}),
        json.dumps({"metric_justifications": "not a dict"}),
    ])
    def test_a_rule_without_usable_reasons_still_scores(self, narrative):
        """A malformed or absent narrative must not cost the reader the
        arithmetic. One bad row taking down the whole detail view would be a
        worse failure than the missing text it was trying to show.
        """
        s = serialize_finding(self._with_narrative(narrative))["scoring"]
        assert s["has_justifications"] is False
        assert all(m["justification"] is None for m in self._by_code(s).values())
        # The part that does not depend on the narrative is unaffected.
        assert s["temporal_score"] == pytest.approx(s["steps"][-1]["value"])

    def test_non_string_reasons_are_dropped_not_rendered(self):
        """Guards the console against printing "[object Object]" — the field is
        typed as text downstream and nothing validates what the pipeline wrote.
        """
        m = self._with_narrative(json.dumps({"metric_justifications": {
            "ac": {"nested": "object"}, "c": ["a", "list"], "i": 42,
            "a": "A=N: availability is untouched."}}))
        metrics = self._by_code(serialize_finding(m)["scoring"])
        assert metrics["AC"]["justification"] is None
        assert metrics["C"]["justification"] is None
        assert metrics["I"]["justification"] is None
        assert metrics["A"]["justification"] == "A=N: availability is untouched."
