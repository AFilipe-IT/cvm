"""
config_assessment/api/routers/knowledge.py
----------------------------------------------
/api/v1/knowledge/... — Knowledge Base explorer, backed by the Knowledge
Engine (a read façade over Database).

Almost all of it is read-only. The exception is attack-chain authoring
(POST/DELETE /chains), which goes through core/engines/chain_authoring so that
a chain written from the console is validated exactly as `caspar chain add`
validates one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from config_assessment.api.deps import get_db, require_api_key
from config_assessment.api.schemas import ChainCreate
from config_assessment.core.db.database import Database
from config_assessment.core.engines import chain_authoring
from config_assessment.core.engines.knowledge import KnowledgeEngine
from config_assessment.core.models import AttackChain, Misconfiguration

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


@router.get("/benchmarks")
def list_benchmarks(db: Database = Depends(get_db)) -> list[dict]:
    """The security benchmarks the knowledge base was built from (CIS, STIG,
    vendor guides) — the provenance behind every rule and score."""
    return KnowledgeEngine(db).list_benchmarks()


@router.get("/targets/{target}/rules", response_model=list[Misconfiguration])
def list_rules(
    target: str, directive: str | None = None, db: Database = Depends(get_db),
) -> list[Misconfiguration]:
    """Every rule CVM knows for one service: the misconfiguration it detects,
    its CCSS vectors and scores, and the remediation. This is the knowledge
    base itself, not the findings of any particular scan. Pass `directive` to
    look up the rules covering a single configuration option."""
    return KnowledgeEngine(db).get_rules_for_target(target, directive=directive)


@router.get("/targets/{target}/rules/{rule_id}", response_model=Misconfiguration)
def get_rule(target: str, rule_id: str, db: Database = Depends(get_db)) -> Misconfiguration:
    """One rule in full — the same content `caspar explain` renders, including
    the scoring justification and the benchmark section it derives from."""
    rule = KnowledgeEngine(db).get_rule_detail(target, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


@router.get("/targets/{target}/chains", response_model=list[AttackChain])
def list_chains(target: str, db: Database = Depends(get_db)) -> list[AttackChain]:
    """The attack chains defined for a service: combinations of findings whose
    combined risk exceeds the sum of their parts, with the amplification
    factor applied when every directive in the chain is present."""
    return KnowledgeEngine(db).list_chains_for_target(target)


@router.post("/chains", response_model=AttackChain,
             status_code=status.HTTP_201_CREATED)
def create_chain_endpoint(
    body: ChainCreate,
    db: Database = Depends(get_db),
    _auth: None = Depends(require_api_key),
) -> AttackChain:
    """Record an attack chain by hand — the equivalent of `caspar chain add`.

    The build pipeline derives chains from benchmarks; this is for the ones an
    operator knows from their own estate. Both go through the same authoring
    engine, so the console and the CLI accept exactly the same chains, and the
    stored chain is marked `provenance: "manual"` so a reader can tell which
    claims came from a person.

    A chain that could never fire is refused rather than stored: 422 carries
    the reason, which is written for the operator, not for a log.
    """
    try:
        return chain_authoring.create_chain(
            db,
            target_name=body.target,
            directives=body.directives,
            justification=body.justification,
            chain_id=body.chain_id,
            amplification=body.amplification,
            author=body.author,
            cross_target=body.cross_target,
            overwrite=body.overwrite,
        )
    except chain_authoring.ChainValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.delete("/targets/{target}/chains/{chain_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def delete_chain_endpoint(
    target: str,
    chain_id: str,
    db: Database = Depends(get_db),
    _auth: None = Depends(require_api_key),
) -> None:
    """Remove a chain definition.

    Scans already stored keep the chain they fired at the time — this deletes
    the definition, not the record of it having matched. A generated chain
    removed here comes back on the next build; a hand-written one does not.
    """
    if not chain_authoring.delete_chain(db, target_name=target, chain_id=chain_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chain not found")
