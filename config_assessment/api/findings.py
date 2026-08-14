"""
config_assessment/api/findings.py
---------------------------------
The shared finding shape (CONTRATO_API_V2.md §3).

`/posture`, `/dimensions/{id}` and `/findings` all return findings, and the
console renders them with one component. Serialising them in three places would
let the three drift apart — a field present here and absent there — so the
mapping from a persisted `Misconfiguration` to the wire lives here once.

WHAT IS ABSENT IS SAID TO BE ABSENT
    A rule built without an LLM narrative has no `title` or `impact`, and a
    finding recovered from a benchmark rather than an observed scan has no
    line number. Those come back `null`, not as an empty string or a
    plausible-looking stand-in: the console distinguishes "no data" from
    "data that happens to be short", and inventing filler here would remove
    its ability to.
"""

from __future__ import annotations

import json

from config_assessment.api.scoring_explain import explain_score
from config_assessment.core.engines import scoring
from config_assessment.core.engines.dimensions import dimension_of

# Wire values for `status` (contract §3). Only `open` is produced today:
# resolution is inferred by a finding's absence from a later scan rather than
# recorded as state, and suppression is applied at scan time by
# `--suppress-file`, so a suppressed finding never reaches the database.
STATUS_OPEN = "open"


def target_labels() -> dict[str, str]:
    """Plugin name → human display name.

    Read from the registered plugins rather than the database: the display
    name is a property of the plugin, and a target row can exist for a plugin
    that is no longer installed. Anything unmatched falls back to its own
    name at serialisation time, so an uninstalled plugin's findings still
    render with something meaningful.
    """
    from config_assessment.core.engines import assessment
    return {p.metadata().name: p.metadata().display_name
            for p in assessment.registered_plugins()}


def _narrative(raw: str | None) -> dict:
    """The Stage-3 LLM narrative, or an empty dict if there is none.

    Rules built with `--no-narratives`, and every deterministic rule, store
    `'{}'`. A malformed value is treated the same way: a finding must still be
    reportable when the enrichment attached to it is broken.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _impact(narrative: dict) -> str | None:
    """`potential_impact` is a list of consequences; the wire wants prose."""
    impact = narrative.get("potential_impact")
    if isinstance(impact, list):
        return " ".join(str(i).rstrip(".") + "." for i in impact if i) or None
    return str(impact) if impact else None


def _evidence(m) -> dict | None:
    """Where the finding was observed.

    Only present for findings that came from an actual scan. A rule sitting in
    the knowledge base has no evidence yet — it describes what WOULD be a
    finding — and saying otherwise would attribute an observation to a file
    nobody read.

    The SHAPE depends on how the directive was observed (contract §3): the
    extra fields differ per kind, and `line`/`snippet` belong to `config_file`
    alone. A file mode has no source line, and reporting one would attribute
    an inode property to a line of text that does not exist.
    """
    directive = getattr(m, "source_directive", None)
    if directive is None:
        return None

    # Collectors fill this in; a directive parsed out of a config file leaves
    # it empty, which is the v1 case and is unchanged below.
    observed = getattr(directive, "evidence", None) or {}
    kind = observed.get("kind", "config_file")

    if kind == "file_metadata":
        return {
            "kind": kind,
            "location": observed.get("location") or directive.source_file or None,
            "mode": observed.get("mode"),
            "owner": observed.get("owner"),
            "group": observed.get("group"),
        }

    if kind == "listening_socket":
        return {
            "kind": kind,
            "location": observed.get("location"),
            "process": observed.get("process"),
            "pid": observed.get("pid"),
            # Passed through rather than re-derived by the consumer: deciding
            # whether an address is reachable means unwrapping IPv4-mapped v6
            # (::ffff:127.0.0.1 IS loopback despite `is_loopback` saying no) and
            # treating the wildcard as world-facing. The collector already does
            # that correctly; a second implementation in the console would be a
            # second place for it to be wrong.
            "world_facing": observed.get("world_facing"),
        }

    return {
        "kind": "config_file",
        "location": directive.source_file or None,
        "line": directive.line_number,
        "snippet": (f"{directive.name} {directive.value}".strip()
                    if directive.name else None),
    }


def _references(m) -> list[dict]:
    refs: list[dict] = []
    if getattr(m, "cis_section", ""):
        refs.append({"label": f"CIS §{m.cis_section}", "url": None})
    if getattr(m, "cce_id", ""):
        refs.append({"label": m.cce_id, "url": None})
    return refs


def serialize_finding(m, *, in_chains: list[str] | None = None,
                      target_label: str | None = None,
                      first_seen: str | None = None) -> dict:
    """One persisted misconfiguration, in the contract's finding shape."""
    narrative = _narrative(getattr(m, "narrative", None))
    score = getattr(m, "temporal_score", 0.0)

    return {
        "id": m.id,
        "dimension": dimension_of(m),
        "target": m.target_name,
        "target_label": target_label or m.target_name,
        "identifier": m.directive,
        "observed_value": m.bad_value,
        "expected_value": m.good_value or None,
        "score": score,
        "severity": scoring.severity_label(score),
        # `description` is the narrative's one-line summary; the justification
        # is the fallback because it is what every rule has, LLM or not.
        "title": narrative.get("description") or getattr(m, "justification", "") or None,
        "impact": _impact(narrative),
        "recommendation": getattr(m, "recommendation", "") or None,
        # The rule's own reason for existing, kept separate from `title` even
        # when the two hold the same text: `title` is what the finding is
        # called, `justification` is why the benchmark says it matters, and a
        # console that shows a score has to be able to show the second without
        # implying it is merely a heading.
        "justification": getattr(m, "justification", "") or None,
        # How the number was arrived at (scoring_explain.py). None when the
        # finding predates the stored vector — the score still renders, the
        # breakdown simply is not claimed.
        "scoring": explain_score(m),
        "evidence": _evidence(m),
        "cves": list(getattr(m, "cves", []) or []),
        "references": _references(m),
        "in_chains": in_chains or [],
        "first_seen": first_seen,
        "status": STATUS_OPEN,
    }


def severity_breakdown(findings) -> dict[str, int]:
    """Counts per severity band, with every band present.

    Bands with no findings are reported as 0 rather than omitted, so the
    console can render a fixed set of bars without inferring that a missing
    key means zero — the same reasoning that keeps unassessed dimensions in
    the posture response.
    """
    counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "None": 0}
    for f in findings:
        label = scoring.severity_label(getattr(f, "temporal_score", 0.0))
        if label in counts:
            counts[label] += 1
    return counts
