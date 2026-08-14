"""
tests/test_chain_authoring.py
------------------------------
Writing attack chains by hand — the engine, the CLI and the REST endpoints.

The property these tests defend is that all three agree. `caspar chain add`
and `POST /knowledge/chains` call one authoring function, so a chain the CLI
refuses must not be storable through the console, and a chain stored either
way must behave in a scan exactly like a generated one.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from config_assessment.core.db.database import Database
from config_assessment.core.engines import chain_authoring
from config_assessment.core.engines.attack_chain import detect_chains
from config_assessment.core.engines.scoring import base_score, temporal_score
from config_assessment.core.models import Misconfiguration, TargetMetadata


@pytest.fixture
def db():
    """A knowledge base with one target and three assessable directives.

    Three, because a chain needs at least two and the interesting failures are
    about the directive that ISN'T there.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)

    database = Database(path)
    database.upsert_target(TargetMetadata(
        name="dummy", display_name="Dummy Target", version="1.0",
        benchmark_source="test fixture",
    ))
    bs = base_score("N", "N", "L", "P", "P", "P")
    ts = temporal_score(bs, "M", "H")
    for directive in ("DangerousOption", "SecondOption", "ThirdOption"):
        database.upsert_misconfiguration(Misconfiguration(
            target_name="dummy", directive=directive, bad_value="on",
            good_value="off", av="N", au="N", ac="L", c="P", i="P", a="P",
            base_score=bs, temporal_score=ts, gel="M", grl="H",
            justification=f"{directive}=on exposes the system.",
            recommendation=f"Set {directive}=off.",
        ))
    yield database
    database.close()
    os.unlink(path)


# ------------------------------------------------------------------ #
# The authoring engine                                                 #
# ------------------------------------------------------------------ #

class TestCreateChain:
    def test_stores_a_valid_chain_as_manual(self, db):
        chain = chain_authoring.create_chain(
            db, target_name="dummy",
            directives=["DangerousOption", "SecondOption"],
            justification="Together they expose the admin surface.",
            author="Alberto Filipe",
        )
        assert chain.provenance == "manual"
        assert chain.author == "Alberto Filipe"

        # And it must survive the round trip: provenance that only exists in
        # the returned object would show correctly once and never again.
        stored = [c for c in db.get_attack_chains("dummy")
                  if c.chain_id == chain.chain_id]
        assert len(stored) == 1
        assert stored[0].provenance == "manual"
        assert stored[0].author == "Alberto Filipe"

    def test_generated_chains_keep_their_provenance(self, db):
        """The build pipeline's chains must not be relabelled as hand-written.

        `upsert_attack_chain` now writes a provenance column; a chain saved by
        the pipeline defaults to "generated", and the whole point of the field
        is lost if everything ends up marked the same way.
        """
        from config_assessment.core.models import AttackChain
        db.upsert_attack_chain(AttackChain(
            chain_id="from-build", target_name="dummy",
            misconfig_directives=["DangerousOption", "SecondOption"],
            justification="Derived from the benchmark.",
        ))
        stored = {c.chain_id: c for c in db.get_attack_chains("dummy")}
        assert stored["from-build"].provenance == "generated"

    def test_preserves_the_declared_directive_order(self, db):
        """Order is the attack's progression, and `detect_chains` reports
        `triggered_by` in exactly this order — a set would scramble it."""
        chain = chain_authoring.create_chain(
            db, target_name="dummy",
            directives=["ThirdOption", "DangerousOption", "SecondOption"],
            justification="Order matters here.",
        )
        assert chain.misconfig_directives == [
            "ThirdOption", "DangerousOption", "SecondOption"]

    def test_drops_duplicate_directives(self, db):
        chain = chain_authoring.create_chain(
            db, target_name="dummy",
            directives=["DangerousOption", "DangerousOption", "SecondOption"],
            justification="Duplicated by accident.",
        )
        assert chain.misconfig_directives == ["DangerousOption", "SecondOption"]

    def test_rejects_a_directive_with_no_rule(self, db):
        """The check that matters most.

        A chain fires only when every directive is present AND at least one is
        a confirmed misconfiguration. A directive CVM has no rule for can never
        satisfy that, so the chain would sit in the database looking real and
        never once match. `caspar doctor` reports this as a warning; refusing it
        at the source is better than storing something inert.
        """
        with pytest.raises(chain_authoring.ChainValidationError) as exc:
            chain_authoring.create_chain(
                db, target_name="dummy",
                directives=["DangerousOption", "NoSuchDirective"],
                justification="Would never fire.",
            )
        assert "NoSuchDirective" in str(exc.value)
        assert db.get_attack_chains("dummy") == []

    def test_rejects_a_single_directive(self, db):
        with pytest.raises(chain_authoring.ChainValidationError):
            chain_authoring.create_chain(
                db, target_name="dummy", directives=["DangerousOption"],
                justification="Not a chain.",
            )

    def test_rejects_an_unknown_target(self, db):
        with pytest.raises(chain_authoring.ChainValidationError) as exc:
            chain_authoring.create_chain(
                db, target_name="nothing-here",
                directives=["DangerousOption", "SecondOption"],
                justification="No such service.",
            )
        # The message lists what IS registered: the usual cause is a typo, and
        # the answer is on screen rather than one more command away.
        assert "dummy" in str(exc.value)

    @pytest.mark.parametrize("justification", ["", "   ", "\n"])
    def test_rejects_an_empty_justification(self, db, justification):
        """Same rule as an accepted risk: an unexplained hand-made claim
        cannot be reviewed by anyone else."""
        with pytest.raises(chain_authoring.ChainValidationError):
            chain_authoring.create_chain(
                db, target_name="dummy",
                directives=["DangerousOption", "SecondOption"],
                justification=justification,
            )

    def test_does_not_silently_replace_an_existing_chain(self, db):
        first = chain_authoring.create_chain(
            db, target_name="dummy",
            directives=["DangerousOption", "SecondOption"],
            justification="The original.", chain_id="collide",
        )
        with pytest.raises(chain_authoring.ChainValidationError):
            chain_authoring.create_chain(
                db, target_name="dummy",
                directives=["DangerousOption", "ThirdOption"],
                justification="A different claim entirely.", chain_id="collide",
            )
        stored = [c for c in db.get_attack_chains("dummy")
                  if c.chain_id == "collide"]
        assert stored[0].justification == first.justification

    def test_overwrite_replaces_it(self, db):
        chain_authoring.create_chain(
            db, target_name="dummy",
            directives=["DangerousOption", "SecondOption"],
            justification="The original.", chain_id="collide",
        )
        chain_authoring.create_chain(
            db, target_name="dummy",
            directives=["DangerousOption", "ThirdOption"],
            justification="Revised.", chain_id="collide", overwrite=True,
        )
        stored = [c for c in db.get_attack_chains("dummy")
                  if c.chain_id == "collide"]
        assert len(stored) == 1, "overwrite must replace, not duplicate"
        assert stored[0].justification == "Revised."

    @pytest.mark.parametrize("bad_id", ["ab", "-leading", "has space", "a" * 65,
                                        "semi;colon"])
    def test_rejects_ids_that_would_not_survive_a_url_or_a_report(self, db, bad_id):
        with pytest.raises(chain_authoring.ChainValidationError):
            chain_authoring.create_chain(
                db, target_name="dummy",
                directives=["DangerousOption", "SecondOption"],
                justification="Fine reason, bad id.", chain_id=bad_id,
            )

    def test_suggested_id_is_stable_for_the_same_directives(self, db):
        """Two operators linking the same directives must land on the same
        name, or the knowledge base fills with near-duplicates."""
        a = chain_authoring.suggest_chain_id("dummy", ["DangerousOption", "SecondOption"])
        b = chain_authoring.suggest_chain_id("dummy", ["DangerousOption", "SecondOption"])
        assert a == b
        assert a.startswith("manual-")


class TestDeleteChain:
    def test_removes_the_definition(self, db):
        chain = chain_authoring.create_chain(
            db, target_name="dummy",
            directives=["DangerousOption", "SecondOption"],
            justification="Temporary.",
        )
        assert chain_authoring.delete_chain(
            db, target_name="dummy", chain_id=chain.chain_id) is True
        assert db.get_attack_chains("dummy") == []

    def test_reports_when_there_was_nothing_to_remove(self, db):
        assert chain_authoring.delete_chain(
            db, target_name="dummy", chain_id="never-existed") is False


# ------------------------------------------------------------------ #
# Detection — a manual chain must behave like any other                #
# ------------------------------------------------------------------ #

class TestManualChainsFire:
    def test_a_manual_chain_fires_like_a_generated_one(self, db):
        """The provenance is for the reader, not for the engine.

        If detection treated hand-written chains differently, the field would
        have changed behaviour rather than described it.
        """
        chain_authoring.create_chain(
            db, target_name="dummy",
            directives=["DangerousOption", "SecondOption"],
            justification="Both together open the admin surface.",
            chain_id="manual-under-test",
        )
        fired = detect_chains(
            active_directives={"DangerousOption", "SecondOption", "Unrelated"},
            misconfig_directives={"DangerousOption"},
            chains=db.get_attack_chains("dummy"),
        )
        assert [c.chain_id for c in fired] == ["manual-under-test"]
        # `triggered_by` is the chain's directives found in the config, in the
        # declared order — not only the ones confirmed as misconfigured.
        assert fired[0].triggered_by == ["DangerousOption", "SecondOption"]

    def test_it_stays_quiet_when_a_directive_is_absent(self, db):
        chain_authoring.create_chain(
            db, target_name="dummy",
            directives=["DangerousOption", "SecondOption"],
            justification="Needs both.", chain_id="needs-both",
        )
        fired = detect_chains(
            active_directives={"DangerousOption"},
            misconfig_directives={"DangerousOption"},
            chains=db.get_attack_chains("dummy"),
        )
        assert fired == []


# ------------------------------------------------------------------ #
# REST                                                                 #
# ------------------------------------------------------------------ #

pytest.importorskip("fastapi", reason="API tests need the [api] extra")


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    from config_assessment.api.app import create_app
    # The engine fixture holds its own connection; the API opens one per
    # request against the same file.
    path = db.conn.execute("PRAGMA database_list").fetchone()[2]
    app = create_app(db_path=path)
    with TestClient(app) as c:
        yield c


class TestChainEndpoints:
    def _body(self, **over):
        body = {
            "target": "dummy",
            "directives": ["DangerousOption", "SecondOption"],
            "justification": "Together they expose the admin surface.",
        }
        body.update(over)
        return body

    def test_post_creates_a_manual_chain(self, client):
        r = client.post("/api/v1/knowledge/chains", json=self._body(
            author="Alberto Filipe"))
        assert r.status_code == 201
        assert r.json()["provenance"] == "manual"
        assert r.json()["author"] == "Alberto Filipe"

    def test_the_new_chain_is_listed_for_its_target(self, client):
        created = client.post(
            "/api/v1/knowledge/chains", json=self._body()).json()
        listed = client.get("/api/v1/knowledge/targets/dummy/chains").json()
        assert created["chain_id"] in [c["chain_id"] for c in listed]

    def test_an_unfireable_chain_is_refused_with_the_reason(self, client):
        """422, and the message is the operator's — it names the directive."""
        r = client.post("/api/v1/knowledge/chains", json=self._body(
            directives=["DangerousOption", "NoSuchDirective"]))
        assert r.status_code == 422
        assert "NoSuchDirective" in r.json()["detail"]

    def test_the_api_refuses_exactly_what_the_cli_refuses(self, client, db):
        """The two surfaces share one validator; this is the test that says so.

        Each case is rejected by the engine directly and over HTTP. If the API
        ever grew its own checks, one of these halves would drift.
        """
        cases = [
            {"directives": ["DangerousOption"]},          # too few
            {"justification": "   "},                     # unexplained
            {"target": "nothing-here"},                   # unknown target
            {"chain_id": "has space"},                    # unusable id
        ]
        for over in cases:
            body = self._body(**over)
            with pytest.raises(chain_authoring.ChainValidationError):
                chain_authoring.create_chain(
                    db, target_name=body["target"],
                    directives=body["directives"],
                    justification=body["justification"],
                    chain_id=body.get("chain_id"),
                )
            assert client.post(
                "/api/v1/knowledge/chains", json=body).status_code == 422

    def test_delete_removes_it(self, client):
        created = client.post(
            "/api/v1/knowledge/chains", json=self._body()).json()
        cid = created["chain_id"]
        assert client.delete(
            f"/api/v1/knowledge/targets/dummy/chains/{cid}").status_code == 204
        listed = client.get("/api/v1/knowledge/targets/dummy/chains").json()
        assert cid not in [c["chain_id"] for c in listed]

    def test_deleting_a_chain_that_is_not_there_is_a_404(self, client):
        r = client.delete("/api/v1/knowledge/targets/dummy/chains/never-existed")
        assert r.status_code == 404
