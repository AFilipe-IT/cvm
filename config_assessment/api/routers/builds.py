"""
config_assessment/api/routers/builds.py
------------------------------------------
POST /api/v1/builds — kick off `caspar build` (LLM-driven knowledge-base
population) as a background job; GET /api/v1/builds lists past build jobs.
Wraps the exact same run_build_job() the CLI command calls — no build logic
duplicated here, just job bookkeeping (202 + job_id, poll via /api/v1/jobs).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from config_assessment.api import job_runner
from config_assessment.api.deps import require_api_key
from config_assessment.api.schemas_jobs import BuildRequest, ProviderInfo

router = APIRouter(prefix="/api/v1/builds", tags=["builds"])

_PROVIDER_LABEL = {
    "ollama": "Ollama (local)",
    "anthropic": "Anthropic Claude",
    "openai": "OpenAI",
}


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_build(body: BuildRequest, request: Request,
                  _auth: None = Depends(require_api_key)) -> dict:
    """Build a knowledge base from a security benchmark, as a background job.

    Returns 202 and a `job_id` immediately — a real build runs an LLM over
    every benchmark rule and can take hours. Poll GET /api/v1/jobs/{job_id}
    for status and .../logs to follow progress. Use `dry_run` to validate the
    inputs without writing rules.

    `provider="ollama"` (the default) needs a reachable Ollama at `ollama_url`;
    the paid providers instead need their key in the server's environment —
    check GET /api/v1/builds/providers before starting one, since a missing key
    fails the job rather than the request.
    """
    from cli.commands.build_cmds import run_build_job

    def target_fn(db_path: str, emit) -> dict:
        count = run_build_job(
            benchmark=body.benchmark, model=body.model, ollama_url=body.ollama_url,
            target=body.target, dry_run=body.dry_run, db_path=db_path, emit=emit,
            provider=body.provider,
        )
        return {"misconfigurations": count}

    job_id = job_runner.start_job(
        request.app.state.db_path, kind="build", params=body.model_dump(),
        target_fn=target_fn,
    )
    return {"job_id": job_id}


@router.get("/providers", response_model=list[ProviderInfo])
def list_providers() -> list[ProviderInfo]:
    """The engines a build can run on, and whether each is ready to use.

    Reports only whether the key VARIABLE is set — never its value, not even
    masked. A console that renders "not configured" next to Anthropic saves an
    operator from starting an hour-long job that would fail on its first call.
    """
    from config_assessment.build.llm_client import (
        API_KEY_ENV, DEFAULT_MODEL, api_key_present,
    )

    return [
        ProviderInfo(
            id=pid,
            label=_PROVIDER_LABEL[pid],
            default_model=DEFAULT_MODEL[pid],
            requires_key=pid in API_KEY_ENV,
            key_env=API_KEY_ENV.get(pid, ""),
            # Ollama needs no key, so it is never "missing" one.
            key_present=api_key_present(pid) if pid in API_KEY_ENV else True,
        )
        for pid in ("ollama", "anthropic", "openai")
    ]


@router.get("")
def list_builds(request: Request) -> list[dict]:
    """Build history — GET /api/v1/jobs?kind=build, kept here so the build
    surface is self-contained."""
    from config_assessment.core.db.database import Database
    with Database(request.app.state.db_path) as db:
        return db.list_jobs(kind="build")
