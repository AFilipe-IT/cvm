"""
cli/commands/chain_cmds.py — writing attack chains by hand.

`caspar chain add/list/remove`. Chains normally come from the build pipeline;
these commands let an operator record a combination the pipeline cannot see —
two settings that are individually tolerable and together are not on their
particular estate.

All three go through config_assessment.core.engines.chain_authoring, which the
REST API also calls, so the CLI and the console cannot disagree about what
makes a chain valid.

Registered on the group in cli/main.py.
"""

from __future__ import annotations

import logging
import sys

import click

logger = logging.getLogger("ccss")


@click.group("chain")
def chain_group() -> None:
    """Define attack chains by hand.

    \b
    An attack chain says that a combination of findings is worse than any of
    them alone. The build pipeline derives chains from benchmarks; these
    commands record the ones you know from your own estate.
      caspar chain list -t nginx
      caspar chain add -t nginx -d server_tokens -d autoindex -r "..."
      caspar chain remove -t nginx manual-nginx-server-tokens-autoindex
    """


@chain_group.command("add")
@click.option("--target", "-t", required=True,
              help="The service the chain belongs to (e.g. nginx).")
@click.option("--directive", "-d", "directives", multiple=True, required=True,
              help="A directive in the chain. Repeat for each one; the order "
                   "given is the order the chain reads in.")
@click.option("--reason", "-r", "justification", required=True,
              help="Why the combination is worse than its parts.")
@click.option("--id", "chain_id", default=None,
              help="Chain identifier (default: derived from the directives).")
@click.option("--author", default="",
              help="Who is asserting this chain.")
@click.option("--amplification", type=float, default=1.0, show_default=True,
              help="Composite multiplier. Left at 1.0 the chain scores as its "
                   "worst constituent finding.")
@click.option("--cross-target", is_flag=True, default=False,
              help="The chain spans more than one service.")
@click.option("--overwrite", is_flag=True, default=False,
              help="Replace an existing chain with the same id.")
@click.pass_context
def chain_add(ctx, target, directives, justification, chain_id, author,
              amplification, cross_target, overwrite) -> None:
    """Record an attack chain linking directives CVM already knows.

    \b
    Each directive must already have a rule for the target — a chain fires only
    when every directive is present and at least one is a confirmed
    misconfiguration, so a directive CVM cannot assess would keep the chain
    from ever matching.
      caspar chain add -t nginx -d server_tokens -d autoindex \\
        -r "Version disclosure plus directory listing hands an attacker a map."
    """
    from config_assessment.core.db.database import Database
    from config_assessment.core.engines.chain_authoring import (
        ChainValidationError, create_chain,
    )

    with Database(ctx.obj["db_path"]) as db:
        try:
            chain = create_chain(
                db,
                target_name=target,
                directives=list(directives),
                justification=justification,
                chain_id=chain_id,
                amplification=amplification,
                author=author,
                cross_target=cross_target,
                overwrite=overwrite,
            )
        except ChainValidationError as exc:
            click.echo(click.style(f"  {exc}", fg="red"), err=True)
            sys.exit(1)

    click.echo()
    click.echo(f"  {click.style('CHAIN ADDED', fg='green', bold=True)}  "
               + click.style(chain.chain_id, bold=True))
    click.echo(f"  Target:     {chain.target_name}")
    click.echo(f"  Directives: {' → '.join(chain.misconfig_directives)}")
    if chain.author:
        click.echo(f"  Author:     {chain.author}")
    click.echo(f"  Reason:     {chain.justification}")
    click.echo()
    click.echo(click.style(
        "  It fires on the next scan, when every directive above is present "
        "in the config and at least one is a confirmed finding.", dim=True))
    click.echo()


@chain_group.command("list")
@click.option("--target", "-t", default=None,
              help="Only this service (default: every registered target).")
@click.option("--manual-only", is_flag=True, default=False,
              help="Only hand-written chains.")
@click.pass_context
def chain_list(ctx, target, manual_only) -> None:
    """List the attack chains defined in the knowledge base.

    \b
    Shows who asserted each one: chains derived by the build pipeline and
    chains written by hand carry different weight.
      caspar chain list
      caspar chain list -t nginx --manual-only
    """
    from config_assessment.core.db.database import Database

    with Database(ctx.obj["db_path"]) as db:
        targets = [target] if target else db.get_target_names()
        rows = []
        for name in targets:
            for c in db.get_attack_chains(name):
                if manual_only and c.provenance != "manual":
                    continue
                rows.append(c)

    if not rows:
        scope = f" for '{target}'" if target else ""
        kind = "manual " if manual_only else ""
        click.echo(click.style(f"  No {kind}chains{scope}.", fg="yellow"))
        return

    click.echo()
    click.echo(f"  {click.style('ATTACK CHAINS', bold=True)}  "
               + click.style(f"({len(rows)})", dim=True))
    click.echo()
    click.echo(f"  {'CHAIN':<38}  {'TARGET':<14}  {'SOURCE':<10}  DIRECTIVES")
    click.echo("  " + "─" * 96)
    for c in rows:
        # Padded before styling: the escape sequences count toward a format
        # spec's width, so `f"{styled:<10}"` would leave the column short.
        label = "manual" if c.provenance == "manual" else "build"
        source = click.style(f"{label:<10}",
                             fg="cyan" if label == "manual" else None,
                             dim=label != "manual")
        click.echo(f"  {c.chain_id:<38}  {c.target_name:<14}  {source}  "
                   f"{' → '.join(c.misconfig_directives)}")
    click.echo()


@chain_group.command("remove")
@click.argument("chain_id")
@click.option("--target", "-t", required=True, help="The chain's service.")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt.")
@click.pass_context
def chain_remove(ctx, chain_id, target, yes) -> None:
    """Delete a chain definition.

    \b
    Scans already stored keep the chain they fired at the time — this removes
    the definition, not the record of it having matched.
      caspar chain remove -t nginx manual-nginx-server-tokens-autoindex
    """
    from config_assessment.core.db.database import Database
    from config_assessment.core.engines.chain_authoring import delete_chain

    with Database(ctx.obj["db_path"]) as db:
        existing = [c for c in db.get_attack_chains(target)
                    if c.chain_id == chain_id]
        if not existing:
            click.echo(click.style(
                f"  No chain '{chain_id}' for target '{target}'.", fg="yellow"),
                err=True)
            sys.exit(1)

        # A generated chain comes back on the next build; a hand-written one is
        # gone for good, so that is the case worth pausing on.
        chain = existing[0]
        if not yes:
            if chain.provenance == "manual":
                click.echo(click.style(
                    "  This chain was written by hand — rebuilding will not "
                    "bring it back.", fg="yellow"))
            click.confirm(f"  Remove chain '{chain_id}' from '{target}'?",
                          abort=True)

        delete_chain(db, target_name=target, chain_id=chain_id)

    click.echo(click.style(f"  ✓ Removed chain '{chain_id}'.", fg="green"))
