"""
core/engines/chain_authoring.py
--------------------------------
Writing an attack chain by hand.

Chains normally come out of the build pipeline, derived from a benchmark. But
an operator often knows a combination the pipeline cannot see — two settings
that are individually tolerable and together are not, on their particular
estate. This is where that knowledge gets written down.

The CLI (`caspar chain add`) and the REST API both call `create_chain` rather
than assembling an `AttackChain` themselves. Validation is the reason: a chain
whose directives do not exist for its target can never fire, and one written
directly through either surface alone would drift from the other's rules.

`KnowledgeEngine` deliberately stays read-only, so this write path lives apart
from it.
"""

from __future__ import annotations

import re

from config_assessment.core.db.database import Database
from config_assessment.core.models import AttackChain

# Chain ids appear in reports, in URLs and in `caspar explain` output, so they
# are restricted to what survives all three without quoting.
_CHAIN_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{2,63}$")


class ChainValidationError(ValueError):
    """A chain that would be stored but could never usefully fire.

    Distinct from a plain ValueError so the API can map it to a 422 while
    letting genuine programming errors surface as 500s.
    """


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return slug[:64]


def suggest_chain_id(target_name: str, directives: list[str]) -> str:
    """A readable default id built from the directives being linked.

    Only a suggestion — `create_chain` takes whatever id it is given. It exists
    so neither the CLI nor the console has to invent an id-naming convention of
    its own, and so two operators linking the same directives land on the same
    name rather than `chain-1` and `my-chain`.
    """
    parts = [_slugify(d) for d in directives if _slugify(d)]
    stem = "-".join(parts[:3]) or "chain"
    return f"manual-{_slugify(target_name)}-{stem}"[:64]


def create_chain(
    db: Database,
    *,
    target_name: str,
    directives: list[str],
    justification: str,
    chain_id: str | None = None,
    amplification: float = 1.0,
    author: str = "",
    cross_target: bool = False,
    overwrite: bool = False,
) -> AttackChain:
    """Validate and store a hand-written attack chain.

    Every check here answers a way the chain could be stored and then be
    useless or misleading, rather than merely malformed:

    - The target must be registered, because `upsert_attack_chain` resolves a
      `target_id` and would otherwise fail with a foreign-key error the author
      cannot act on.
    - At least two directives, because a "chain" of one is a finding. The whole
      claim of a chain is that the combination is worse than the parts.
    - Every directive must exist as a rule for that target. A chain fires only
      when ALL of its directives are present in the parsed config AND at least
      one is a confirmed misconfiguration (see engines/attack_chain.py); a
      directive CVM has no rule for can never satisfy the second condition, so
      the chain would sit in the database and never once fire. `caspar doctor`
      reports exactly this as a warning — better to refuse it at the source.
    - A written justification, for the same reason an exception requires a
      reason: an unexplained hand-made claim cannot be reviewed by anyone else.
    - An existing id is not silently replaced. Overwriting someone's chain
      because the id collided is a destructive default.

    Amplification is accepted but not published anywhere in the console — see
    cli/_output.py; the score already reflects it and the multiplier itself is
    a curated constant rather than a measured quantity. Left at 1.0, a manual
    chain scores exactly as its worst constituent finding.
    """
    target_name = target_name.strip()
    if not target_name:
        raise ChainValidationError("A target name is required.")
    if db.get_target_id(target_name) is None:
        known = ", ".join(db.get_target_names()) or "none registered"
        raise ChainValidationError(
            f"Unknown target '{target_name}'. Known targets: {known}."
        )

    # Preserve the author's order — it reads as the attack's progression, and
    # `detect_chains` reports `triggered_by` in exactly this order.
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in directives:
        directive = raw.strip()
        if directive and directive not in seen:
            seen.add(directive)
            ordered.append(directive)

    if len(ordered) < 2:
        raise ChainValidationError(
            "A chain links at least two distinct directives — with one, the "
            "finding already says everything the chain would."
        )

    known_directives = {
        rule.directive for rule in db.get_all_misconfigurations(target_name)
    }
    missing = [d for d in ordered if d not in known_directives]
    if missing:
        raise ChainValidationError(
            f"No rule for {', '.join(missing)} on target '{target_name}'. A "
            "chain only fires when each of its directives can be assessed, so "
            "this one would never match anything."
        )

    if not justification.strip():
        raise ChainValidationError(
            "A justification is required: it is what lets someone else judge "
            "whether the combination really is worse than its parts."
        )

    if not 1.0 <= amplification <= 10.0:
        raise ChainValidationError("Amplification must be between 1.0 and 10.0.")

    final_id = (chain_id or suggest_chain_id(target_name, ordered)).strip()
    if not _CHAIN_ID_RE.match(final_id):
        raise ChainValidationError(
            f"Invalid chain id '{final_id}'. Use 3-64 characters: letters, "
            "digits, dot, hyphen or underscore, starting with a letter or digit."
        )

    existing = {c.chain_id for c in db.get_attack_chains(target_name)}
    if final_id in existing and not overwrite:
        raise ChainValidationError(
            f"Chain '{final_id}' already exists for '{target_name}'. Pass "
            "overwrite to replace it."
        )

    chain = AttackChain(
        chain_id=final_id,
        target_name=target_name,
        misconfig_directives=ordered,
        amplification=amplification,
        justification=justification.strip(),
        cross_target=cross_target,
        provenance="manual",
        author=author.strip(),
    )
    db.upsert_attack_chain(chain)
    return chain


def delete_chain(db: Database, *, target_name: str, chain_id: str) -> bool:
    """Remove a chain definition. False when there was nothing to remove."""
    return db.delete_attack_chain(target_name, chain_id)
