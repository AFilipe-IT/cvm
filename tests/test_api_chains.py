"""
tests/test_api_chains.py
------------------------
Tests for GET /api/v1/chains — the v2 chain shape.

Two things are under test, and they are the two that a typecheck cannot catch.

FIRST, THE V1 ROUTE IS NOT DISTURBED. `GET /scans/{id}/chains` returns the
stored `AttackChain` verbatim (`chain_id`, `amplified_score`, `justification`)
and its consumers depend on exactly those names. The API is additive-only, so
the v2 shape is a second endpoint, and a test asserts both shapes coexist —
otherwise a later "cleanup" that renames the v1 fields would look harmless.

SECOND, A STEP ALWAYS RESOLVES TO A FINDING. A chain fires on directives, but
the console links each step to the finding it became. A directive that produced
no finding is dropped rather than rendered as a placeholder, because a step the
reader cannot open is an assertion with nothing behind it.
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
        benchmark_source="chains test fixture",
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
    # `Listen` is deliberately NOT a misconfiguration: the chain names two
    # directives but only one of them becomes a finding, which is the case the
    # step resolution has to handle honestly.
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

class TestChainShape:
    def test_every_contract_field_is_present(self, client, dummy_config_file):
        _scan(client, dummy_config_file)
        chains = client.get("/api/v1/chains").json()
        assert chains, "the fixture chain should have triggered"

        chain = chains[0]
        assert set(chain) == {
            "id", "title", "score", "severity", "active", "amplification",
            "exceeds_overall", "cross_dimension", "narrative", "steps",
        }
        assert chain["id"] == "test-chain"
        assert chain["active"] is True
        assert chain["narrative"] == "Combined attack path."
        # Un-slugged from the id rather than invented: the engine wrote no
        # title, and showing a raw slug in a heading is worse than either.
        assert chain["title"] == "Test chain"

    def test_severity_matches_the_score(self, client, dummy_config_file):
        _scan(client, dummy_config_file)
        chain = client.get("/api/v1/chains").json()[0]
        from config_assessment.core.engines import scoring
        assert chain["severity"] == scoring.severity_label(chain["score"])

    def test_nothing_assessed_means_no_chains(self, client):
        """An empty list, not an error. No scan means no chain — that is a
        result, not a failure."""
        r = client.get("/api/v1/chains")
        assert r.status_code == 200
        assert r.json() == []


# ── steps ──────────────────────────────────────────────────────────────

class TestChainSteps:
    def test_each_step_resolves_to_a_real_finding(self, client, dummy_config_file):
        _scan(client, dummy_config_file)
        chain = client.get("/api/v1/chains").json()[0]
        finding_ids = {f["id"]
                       for f in client.get("/api/v1/findings").json()["findings"]}

        assert chain["steps"], "a chain with no linkable step is not renderable"
        for step in chain["steps"]:
            assert set(step) == {"order", "finding_id", "dimension",
                                 "identifier", "score", "role"}
            assert step["finding_id"] in finding_ids, \
                "a step must open to a finding the console can actually show"

    def test_a_directive_with_no_finding_is_dropped_not_faked(
            self, client, dummy_config_file):
        """`Listen` triggers the chain but produced no misconfiguration.

        Emitting it with a null finding_id would put a row in the console that
        opens onto nothing; omitting it says only what the evidence supports.
        """
        _scan(client, dummy_config_file)
        chain = client.get("/api/v1/chains").json()[0]
        identifiers = [s["identifier"] for s in chain["steps"]]
        assert "DangerousOption" in identifiers
        assert "Listen" not in identifiers

    def test_order_is_contiguous_from_one(self, client, dummy_config_file):
        """Dropping an unresolvable directive must not leave a gap: the order
        is the reading order of what is shown, not an index into the raw
        directive list."""
        _scan(client, dummy_config_file)
        chain = client.get("/api/v1/chains").json()[0]
        assert [s["order"] for s in chain["steps"]] == \
            list(range(1, len(chain["steps"]) + 1))

    def test_a_single_step_chain_is_impact_not_entry(
            self, client, dummy_config_file):
        """One directive is not a sequence. Calling it `entry` would imply a
        next step that does not exist."""
        _scan(client, dummy_config_file)
        chain = client.get("/api/v1/chains").json()[0]
        if len(chain["steps"]) == 1:
            assert chain["steps"][0]["role"] == "impact"


# ── agreement with /posture ────────────────────────────────────────────

class TestChainsAgreeWithPosture:
    def test_count_matches_the_posture_summary(self, client, dummy_config_file):
        """Same scoping, so the two cannot drift: a chain listed here is one of
        the `active_count` the posture page reports."""
        _scan(client, dummy_config_file)
        chains = client.get("/api/v1/chains").json()
        posture = client.get("/api/v1/posture").json()
        assert len(chains) == posture["chains"]["active_count"]
        assert max(c["score"] for c in chains) == \
            posture["chains"]["highest_score"]

    def test_exceeds_overall_is_measured_against_the_shown_score(
            self, client, dummy_config_file):
        """The flag has to compare against the number the operator actually
        sees at the top of the page, or it flags against nothing."""
        _scan(client, dummy_config_file)
        chains = client.get("/api/v1/chains").json()
        overall = client.get("/api/v1/posture").json()["overall"]["score"]
        for chain in chains:
            assert chain["exceeds_overall"] == (chain["score"] > overall)


# ── the v1 route is untouched ──────────────────────────────────────────

class TestV1ChainsStillWork:
    def test_the_stored_shape_is_unchanged(self, client, dummy_config_file):
        """The API is additive-only. The v2 shape is a second endpoint, not a
        rename of this one — its consumers read `chain_id`/`amplified_score`."""
        scan = _scan(client, dummy_config_file)
        v1 = client.get(f"/api/v1/scans/{scan['scan_id']}/chains").json()
        assert v1, "the fixture chain should be on the scan"
        assert "chain_id" in v1[0]
        assert "amplified_score" in v1[0]
        assert "justification" in v1[0]
        # The v1 names are exactly the ones v2 renames; if these ever appear
        # here, the two shapes have been merged and this test is the warning.
        assert "id" not in v1[0]
        assert "steps" not in v1[0]
