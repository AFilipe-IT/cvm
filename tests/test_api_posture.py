"""
tests/test_api_posture.py
-------------------------
Tests for GET /api/v1/posture.

The engine's own semantics are covered in test_dimensions.py; what is under
test here is that the HTTP layer carries them out intact — above all that a
dimension nobody assessed arrives as `null`, never as 0.0. A `0.0` on the wire
renders green in the console, so a serialisation bug here would undo the whole
model even with the engine behaving correctly.
"""

from __future__ import annotations

import os
import tempfile

import pytest
pytest.importorskip("fastapi", reason="API tests need the [api] extra "
                    "(pip install -e '.[dev]')")

from fastapi.testclient import TestClient  # noqa: E402

from config_assessment.core import runtime
from config_assessment.core.db.database import Database
from config_assessment.core.engines.dimensions import DIMENSION_IDS
from config_assessment.core.engines.scoring import base_score, temporal_score
from config_assessment.core.models import AttackChain, Misconfiguration, TargetMetadata


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
        benchmark_source="posture test fixture",
    ))
    bs = base_score("N", "N", "L", "P", "P", "P")
    ts = temporal_score(bs, "M", "H")
    database.upsert_misconfiguration(Misconfiguration(
        target_name="dummy", directive="DangerousOption", bad_value="on",
        good_value="off", av="N", au="N", ac="L", c="P", i="P", a="P",
        base_score=bs, temporal_score=ts, gel="M", grl="H",
        cves=["CVE-2023-00001"],
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


def _scan(client, path):
    r = client.post("/api/v1/scans", json={"input_path": path})
    assert r.status_code in (200, 201), r.text
    return r.json()


# ── shape ──────────────────────────────────────────────────────────────

class TestPostureShape:
    def test_every_dimension_is_reported_in_contract_order(self, client):
        body = client.get("/api/v1/posture").json()
        assert [d["id"] for d in body["dimensions"]] == list(DIMENSION_IDS)

    def test_the_model_declares_how_it_scored(self, client):
        model = client.get("/api/v1/posture").json()["scoring_model"]
        assert model["version"] == "2.0"
        assert model["missing_dimension_policy"] == "excluded"
        assert model["aggregation"] == "weighted"

    def test_coverage_is_reported_as_a_percentage(self, client, dummy_config_file):
        _scan(client, dummy_config_file)
        cov = client.get("/api/v1/posture").json()["coverage"]
        assert cov["dimensions_total"] == len(DIMENSION_IDS)
        assert cov["dimensions_assessed"] == 1
        assert cov["percent"] == 17  # 1/6

    def test_an_unknown_host_is_a_404(self, client):
        assert client.get("/api/v1/posture?host_id=999").status_code == 404

    def test_the_manifest_records_what_produced_the_score(self, client,
                                                          dummy_config_file):
        _scan(client, dummy_config_file)
        m = client.get("/api/v1/posture").json()["manifest"]
        assert m["db_sha256"], "the knowledge base the scores came from"
        assert m["python"]
        assert m["scoring_model_version"] == "2.0"

    def test_disagreeing_manifests_report_null_rather_than_picking_one(self, client):
        """A posture spans several scans. When they came from different
        knowledge bases the aggregate is not reproducible from one state, and
        saying so beats reporting whichever hash happened to sort first."""
        from config_assessment.api.routers.posture import _manifest

        class R:
            def __init__(self, m): self.manifest = m

        agreeing = _manifest([R({"db_sha256": "aaa"}), R({"db_sha256": "aaa"})])
        assert agreeing["db_sha256"] == "aaa"

        differing = _manifest([R({"db_sha256": "aaa"}), R({"db_sha256": "bbb"})])
        assert differing["db_sha256"] is None
        # The scoring model is this build's, so it is known even then.
        assert differing["scoring_model_version"] == "2.0"


# ── the distinction, over HTTP ─────────────────────────────────────────

class TestNotAssessedSurvivesSerialization:
    def test_unassessed_dimensions_arrive_as_null_not_zero(self, client,
                                                           dummy_config_file):
        """A 0.0 on the wire renders green. Only `null` says 'never looked'."""
        _scan(client, dummy_config_file)
        by_id = {d["id"]: d for d in client.get("/api/v1/posture").json()["dimensions"]}

        for dim_id in ("secrets", "exposure", "hardening", "patch", "permissions"):
            d = by_id[dim_id]
            assert d["status"] == "not_assessed"
            assert d["score"] is None, f"{dim_id} must not report a number"
            assert d["severity"] is None
            assert d["assessed_at"] is None

    def test_an_unassessed_dimension_explains_itself(self, client):
        by_id = {d["id"]: d for d in client.get("/api/v1/posture").json()["dimensions"]}
        assert by_id["secrets"]["not_assessed_reason"]

    def test_an_assessed_dimension_carries_a_real_number(self, client,
                                                         dummy_config_file):
        _scan(client, dummy_config_file)
        by_id = {d["id"]: d for d in client.get("/api/v1/posture").json()["dimensions"]}
        config = by_id["configuration"]
        assert config["status"] == "assessed"
        assert config["score"] > 0
        assert config["severity"]
        assert config["findings_count"] >= 1
        assert config["assessed_at"]

    def test_nothing_scanned_is_reported_as_such_not_as_unimplemented(self, client):
        """The engine can only explain a missing implementation. Saying
        configuration assessment "is not implemented" to someone who simply has
        not scanned yet sends them hunting for a feature that is already there."""
        by_id = {d["id"]: d for d in client.get("/api/v1/posture").json()["dimensions"]}
        assert "has been run" in by_id["configuration"]["not_assessed_reason"]
        # An unimplemented dimension keeps its own, different explanation.
        assert "not implemented" in by_id["secrets"]["not_assessed_reason"]

    def test_an_empty_database_yields_no_score_at_all(self, client):
        """Nothing scanned means there is nothing to report — not a clean 0.0,
        which would advertise a safety that was never checked."""
        body = client.get("/api/v1/posture").json()
        assert body["overall"]["score"] is None
        assert body["overall"]["severity"] is None
        assert body["coverage"]["dimensions_assessed"] == 0
        assert all(d["status"] == "not_assessed" for d in body["dimensions"])


# ── the numbers ────────────────────────────────────────────────────────

class TestPostureNumbers:
    def test_the_overall_matches_the_only_assessed_dimension(self, client,
                                                             dummy_config_file):
        """With one dimension assessed, renormalisation leaves its own score
        untouched — the unassessed five must not drag it toward zero."""
        _scan(client, dummy_config_file)
        body = client.get("/api/v1/posture").json()
        by_id = {d["id"]: d for d in body["dimensions"]}
        assert body["overall"]["score"] == by_id["configuration"]["score"]

    def test_the_driver_names_the_finding_behind_the_score(self, client,
                                                           dummy_config_file):
        """The mean must not cost the actionability v1 guaranteed."""
        _scan(client, dummy_config_file)
        driver = client.get("/api/v1/posture").json()["overall"]["driver"]
        assert driver["kind"] == "finding"
        assert driver["dimension"] == "configuration"
        assert "DangerousOption" in driver["label"]
        assert driver["score"] > 0
        # The id is what lets the console link straight to it.
        assert driver["finding_id"]
        listed = client.get("/api/v1/findings").json()["findings"]
        assert driver["finding_id"] in {f["id"] for f in listed}, \
            "the driver must point at a finding the client can actually fetch"

    def test_no_findings_means_no_driver(self, client):
        assert client.get("/api/v1/posture").json()["overall"]["driver"] is None

    def test_the_delta_is_null_rather_than_a_fabricated_zero(self, client,
                                                             dummy_config_file):
        """No per-dimension history is persisted yet, so there is no basis for
        comparison. 0.0 would claim stability that was never measured."""
        _scan(client, dummy_config_file)
        body = client.get("/api/v1/posture").json()
        assert body["overall"]["delta"] is None
        assert all(d["delta"] is None for d in body["dimensions"])

    def test_totals_count_what_was_actually_found(self, client, dummy_config_file):
        _scan(client, dummy_config_file)
        totals = client.get("/api/v1/posture").json()["totals"]
        assert totals["targets_assessed"] == 1
        assert totals["findings_open"] >= 1
        # Distinct CVEs, not a sum over findings: one CVE cited by three
        # findings is one CVE, and counting it three times would overstate
        # the exposure.
        assert totals["related_cves"] == 1

    def test_rules_evaluated_counts_what_was_examined_not_what_exists(
            self, client, dummy_config_file):
        """Counting knowledge-base rules instead of examined directives would
        inflate apparent coverage — the same error not_assessed prevents."""
        _scan(client, dummy_config_file)
        totals = client.get("/api/v1/posture").json()["totals"]
        assert totals["rules_evaluated"] >= totals["findings_open"]
        scanned = client.get("/api/v1/scans").json()
        rows = scanned["scans"] if isinstance(scanned, dict) else scanned
        assert totals["rules_evaluated"] == rows[0]["total_directives"]

    def test_repeated_scans_of_one_file_count_once(self, client, dummy_config_file):
        """A file scanned nightly must not outweigh one scanned once."""
        _scan(client, dummy_config_file)
        first = client.get("/api/v1/posture").json()
        _scan(client, dummy_config_file)
        again = client.get("/api/v1/posture").json()
        assert again["totals"]["targets_assessed"] == 1
        assert again["totals"]["findings_open"] == first["totals"]["findings_open"]


# ── chains ─────────────────────────────────────────────────────────────

class TestPostureChains:
    def test_chains_are_reported_without_being_folded_into_the_score(
            self, client, dummy_config_file):
        """Chains still do not raise the overall — the v1 decision stands.
        Reporting them separately is how the console shows one outranking it
        instead of silently averaging it in."""
        _scan(client, dummy_config_file)
        body = client.get("/api/v1/posture").json()
        chains = body["chains"]
        assert chains["active_count"] >= 1
        assert chains["highest_score"] > body["overall"]["score"]
        assert chains["exceeds_overall"] is True

    def test_no_chains_means_no_comparison(self, client):
        chains = client.get("/api/v1/posture").json()["chains"]
        assert chains["active_count"] == 0
        assert chains["highest_score"] is None
        assert chains["exceeds_overall"] is False


# ── host scoping ───────────────────────────────────────────────────────

class TestPostureByHost:
    def test_a_host_sees_only_its_own_findings(self, client, dummy_config_file):
        # A scan attaches to a host by LABEL (`host`), which the scan router
        # resolves to an id; the posture endpoint scopes by that id.
        r = client.post("/api/v1/scans",
                        json={"input_path": dummy_config_file, "host": "web01"})
        assert r.status_code in (200, 201), r.text
        registry = client.get("/api/v1/hosts/registry").json()
        host_id = next(h["id"] for h in registry if h["label"] == "web01")

        other = client.post("/api/v1/hosts/registry",
                            json={"label": "web02"}).json()["id"]

        scoped = client.get(f"/api/v1/posture?host_id={host_id}").json()
        assert scoped["overall"]["score"] is not None

        empty = client.get(f"/api/v1/posture?host_id={other}").json()
        assert empty["overall"]["score"] is None, \
            "a host that was never scanned has no posture, not a clean one"
        assert empty["coverage"]["dimensions_assessed"] == 0


# ── which dimensions a scan actually assessed ──────────────────────────

class TestAssessedDimensionsFollowTheTarget:
    """Being able to assess a dimension is not the same as having assessed it.

    Scanning an nginx.conf examines no inode and no socket, so permissions and
    exposure must come back `not_assessed` — reporting them clean off the back
    of a config-file scan is precisely the failure the model exists to prevent,
    and it is the failure a build-wide "implemented" flag would reintroduce.
    """

    @staticmethod
    def _result(target_name):
        class R:
            pass
        r = R()
        r.target_name = target_name
        return r

    def test_a_config_only_target_assesses_configuration_alone(self):
        from config_assessment.api.routers.posture import assessed_dimensions
        assert assessed_dimensions([self._result("nginx")]) == {"configuration"}

    def test_the_system_state_target_assesses_all_three(self):
        from config_assessment.api.routers.posture import assessed_dimensions
        assert assessed_dimensions([self._result("ubuntu2204")]) == {
            "configuration", "permissions", "exposure"}

    def test_coverage_is_the_union_across_scans(self):
        """A host scanned with both has had its config AND its system state
        examined, and the posture should say so."""
        from config_assessment.api.routers.posture import assessed_dimensions
        assert assessed_dimensions([
            self._result("nginx"), self._result("ubuntu2204"),
        ]) == {"configuration", "permissions", "exposure"}

    def test_no_scans_assess_nothing(self):
        from config_assessment.api.routers.posture import assessed_dimensions
        assert assessed_dimensions([]) == frozenset()

    def test_an_unknown_target_claims_only_configuration(self):
        """A plugin added later must not be assumed to collect system state."""
        from config_assessment.api.routers.posture import assessed_dimensions
        assert assessed_dimensions([self._result("some-future-plugin")]) == {
            "configuration"}

    def test_a_config_scan_leaves_permissions_unassessed_over_http(
            self, client, dummy_config_file):
        r = client.post("/api/v1/scans", json={"input_path": dummy_config_file})
        assert r.status_code in (200, 201), r.text

        body = client.get("/api/v1/posture").json()
        by_id = {d["id"]: d for d in body["dimensions"]}
        assert by_id["configuration"]["status"] != "not_assessed"
        for dim in ("permissions", "exposure"):
            assert by_id[dim]["status"] == "not_assessed", \
                f"{dim} was never examined by a config-file scan"
            assert by_id[dim]["score"] is None

    def test_an_implementable_dimension_says_so_rather_than_not_implemented(
            self, client):
        """With nothing scanned, permissions is unassessed because nobody ran
        a scan — not because the build lacks the feature. Saying 'not
        implemented' would send an operator hunting for a feature that is
        right there."""
        body = client.get("/api/v1/posture").json()
        by_id = {d["id"]: d for d in body["dimensions"]}
        assert "has been run" in by_id["permissions"]["not_assessed_reason"]
        assert "not implemented" in by_id["patch"]["not_assessed_reason"].lower()
