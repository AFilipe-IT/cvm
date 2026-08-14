"""
config_assessment/api/schemas.py
----------------------------------
Request/response schemas specific to the REST API layer. ScanResult,
Misconfiguration, AttackChain, SystemProfile etc. are used directly from
config_assessment.core.models as response models — no adapter layer.
This module only adds the request bodies the CVM Core has no model for.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from config_assessment.core.models import ScanResult


class ScanRequest(BaseModel):
    input_path: str
    live: bool = False
    version: str | None = None
    env_profile: Literal["production", "internal", "dev"] | None = None
    host: str | None = None
    threshold: float = 0.0
    suppress_file: str | None = None
    assess_unknown: bool = False
    docs_path: str | None = None


class ScanResponse(ScanResult):
    """ScanResult plus API-only, CLI-`scan`-equivalent outcome fields.

    A strict superset (existing ScanResult consumers still parse this fine).
    Mirrors what `caspar scan`'s CI flags (--threshold, --suppress-file,
    --assess-unknown) print/decide, as data instead of an exit code."""
    passed_threshold: bool = True
    suppressed_count: int = 0


class HostCreate(BaseModel):
    label: str


class ReportRequest(BaseModel):
    format: Literal["html", "dashboard", "sarif", "json"] = "html"
    online: bool = False


class ChainCreate(BaseModel):
    """A hand-written attack chain — the request half of `caspar chain add`.

    `target` and `directives` are not validated here beyond their shape: what
    makes a chain valid is whether those directives have rules in THIS
    knowledge base, which only the engine can answer. Splitting the checks
    between this model and the engine would let the API and the CLI accept
    different chains.
    """
    target: str
    directives: list[str]
    justification: str
    chain_id: str | None = None
    author: str = ""
    amplification: float = 1.0
    cross_target: bool = False
    # A collision means an id already in use. Replacing it by default would
    # overwrite someone else's chain, so the caller has to ask.
    overwrite: bool = False


class HealthResponse(BaseModel):
    status: Literal["ok"]
    db_reachable: bool
    plugins_registered: int
