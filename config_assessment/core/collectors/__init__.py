"""
config_assessment/core/collectors/
----------------------------------
Collectors observe SYSTEM STATE and express it as `Directive`s.

WHY THIS IS NOT A NEW PIPELINE
    The v1 scan matches a directive against the knowledge base on
    `(target, name, value)` alone — `engines/assessment.py::match_value_rules`
    never asks where the directive came from. So system state does not need a
    parallel scoring path: it needs to be expressed as directives, and the
    existing engine scores it unchanged. That keeps one scoring path for every
    dimension, which is what makes cross-dimension comparison meaningful.

THE NAMING RULE
    A directive name must be STABLE and CONTENT-ADDRESSED, because it is the
    join key against the knowledge base. Collectors therefore name a directive
    after the thing observed, not after the observation:

        file_mode:/etc/shadow      value "0644"
        listen:0.0.0.0:8080        value "nginx"

    The rule for `/etc/shadow`'s mode is written once and matches whatever
    mode is found. Encoding the observed value into the name instead
    (`shadow_is_0644`) would need one rule per possible mode, which is not a
    knowledge base but a lookup table.

WHAT A COLLECTOR MUST NOT DO
    Report an empty result when it could not look. A collector that cannot
    read /proc, or is pointed at a mounted image where sockets have no
    meaning, raises `CollectorUnavailable` — it does not return `[]`. An empty
    list means "looked, found nothing", and the whole dimension model rests on
    that distinction being real.
"""

from __future__ import annotations


class CollectorUnavailable(RuntimeError):
    """Raised when a collector cannot observe what it is meant to observe.

    Distinct from returning an empty list, which asserts that the observation
    succeeded and found nothing. Callers turn this into `not_assessed`, never
    into a clean result.
    """
