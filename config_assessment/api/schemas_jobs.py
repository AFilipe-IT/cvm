"""
config_assessment/api/schemas_jobs.py
----------------------------------------
Request/response schemas for the background-job surface (builds, plugin
installs, and the generic job/log polling endpoints). Split out of
schemas.py, which is scoped to the synchronous scan/report/host surface.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class BuildRequest(BaseModel):
    benchmark: str
    target: Literal["apache-httpd", "nginx"] = "apache-httpd"
    model: str = "qwen2.5:14b"
    ollama_url: str = "http://localhost:11434"
    dry_run: bool = False
    # Which engine runs the build. There is deliberately NO api_key field: the
    # hosted providers read their key from the server's environment. A key sent
    # here would be stored verbatim in the job's params_json and echoed back by
    # GET /jobs — see llm_client's module docstring.
    provider: Literal["ollama", "anthropic", "openai"] = "ollama"


class ProviderInfo(BaseModel):
    """One build engine, as the console needs to render its choice."""
    id: str
    label: str
    default_model: str
    #: Whether this provider needs a key at all (Ollama does not).
    requires_key: bool
    #: The environment variable the key is read from, "" when none is needed.
    key_env: str
    #: Whether that variable is set in the server's environment. Never the key.
    key_present: bool


class PluginInstallRequest(BaseModel):
    source: str
    manual: str | None = None
    dry_run: bool = False
    no_llm: bool = False
    model: str = "qwen2.5:14b"


JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class PluginManualRequest(BaseModel):
    """`caspar plugin manual` — the *retroactive* RAG-ingest path, for a
    plugin that is already installed (`plugin add --manual` covers ingest at
    install time)."""
    target: str
    # A local server-side path or an http(s) URL, exactly as the CLI accepts.
    manual: str


class JobResponse(BaseModel):
    id: str
    kind: str
    status: JobStatus
    params_json: str
    result_json: str | None = None
    error: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class JobLogLine(BaseModel):
    seq: int
    ts: str
    line: str
