"""
tests/test_llm_providers.py
---------------------------
The paid build engines (Anthropic, OpenAI) and how the build chooses between
them.

Nothing here touches a provider. Every test either stubs urlopen or asserts on
what happens BEFORE a request is made — which is where most of the value is:
the interesting behaviour of a paid backend is that it refuses to start when it
cannot succeed, rather than failing an hour and a hundred euros later.

The property these tests exist to protect: an API key lives in the server's
environment and NOWHERE else. Not in a request body, not in a job's params, not
in an error message, not in a log line.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from config_assessment.build import llm_client as lc
from config_assessment.build.llm_client import (
    API_KEY_ENV,
    DEFAULT_MODEL,
    HostedClient,
    OllamaClient,
    StubLLMClient,
    api_key_present,
    make_client,
)


class _FakeResponse:
    """Minimal stand-in for the object urlopen returns as a context manager."""

    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def _capture(monkeypatch, payload: dict) -> dict:
    """Stub urlopen, returning `payload`, and record the request it was given."""
    seen: dict = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.headers)
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(payload)

    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
    return seen


# ------------------------------------------------------------------ #
# The key never leaves the environment                                 #
# ------------------------------------------------------------------ #

class TestKeyHandling:

    def test_a_missing_key_fails_before_any_work_happens(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(RuntimeError) as exc:
            make_client(backend="anthropic")
        # The message has to say which variable to set — "auth failed" would
        # leave the operator guessing at the one thing they must change.
        assert "ANTHROPIC_API_KEY" in str(exc.value)

    def test_the_key_is_read_from_the_environment_not_an_argument(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-env")
        client = make_client(backend="openai")
        seen = _capture(monkeypatch, {
            "choices": [{"message": {"content": "hello"}}]})
        client.complete("prompt")
        assert seen["headers"]["Authorization"] == "Bearer sk-from-the-env"

    def test_a_rejected_key_is_reported_without_repeating_it(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-wrong-value")

        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 401, "Unauthorized", hdrs=None, fp=None)

        monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
        client = make_client(backend="anthropic")

        with pytest.raises(RuntimeError) as exc:
            client.complete("prompt")
        message = str(exc.value)
        assert "ANTHROPIC_API_KEY" in message      # says what to fix
        assert "sk-ant-wrong-value" not in message  # without echoing it

    def test_api_key_present_reports_presence_only(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-something")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert api_key_present("openai") is True
        assert api_key_present("anthropic") is False
        # A variable set to whitespace is not a key.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
        assert api_key_present("anthropic") is False

    def test_every_hosted_provider_has_a_declared_key_variable(self):
        """DEFAULT_MODEL and API_KEY_ENV must not drift: a provider present in
        one and missing from the other is either an unusable choice in the UI
        or a key read from nowhere."""
        hosted = set(DEFAULT_MODEL) - {"ollama"}
        assert hosted == set(API_KEY_ENV)


# ------------------------------------------------------------------ #
# The two hosted APIs differ; one class covers both                    #
# ------------------------------------------------------------------ #

class TestHostedRequests:

    def test_anthropic_sends_the_system_prompt_as_its_own_field(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        client = make_client(backend="anthropic", model="claude-sonnet-4-5")
        seen = _capture(monkeypatch, {
            "content": [{"type": "text", "text": "answer"}]})

        assert client.complete("the prompt", "the system") == "answer"
        assert seen["url"] == "https://api.anthropic.com/v1/messages"
        assert seen["body"]["system"] == "the system"
        assert seen["body"]["messages"] == [
            {"role": "user", "content": "the prompt"}]
        assert seen["headers"]["Anthropic-version"] == "2023-06-01"

    def test_openai_sends_the_system_prompt_as_the_first_message(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        client = make_client(backend="openai", model="gpt-4o")
        seen = _capture(monkeypatch, {
            "choices": [{"message": {"content": "answer"}}]})

        assert client.complete("the prompt", "the system") == "answer"
        assert seen["url"] == "https://api.openai.com/v1/chat/completions"
        assert "system" not in seen["body"]
        assert seen["body"]["messages"][0] == {
            "role": "system", "content": "the system"}

    def test_anthropic_joins_only_the_text_blocks(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        client = make_client(backend="anthropic")
        _capture(monkeypatch, {"content": [
            {"type": "text", "text": "part one "},
            {"type": "thinking", "thinking": "ignored"},
            {"type": "text", "text": "part two"},
        ]})
        assert client.complete("p") == "part one part two"

    def test_a_rate_limit_is_retried_but_a_bad_request_is_not(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setattr(lc.time, "sleep", lambda *_: None)
        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            raise urllib.error.HTTPError(
                req.full_url, 429, "Too Many Requests", hdrs=None, fp=None)

        monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(RuntimeError):
            make_client(backend="openai").complete("p")
        assert calls["n"] == 3          # 429 is transient: retried

        calls["n"] = 0

        def bad_request(req, timeout=None):
            calls["n"] += 1
            raise urllib.error.HTTPError(
                req.full_url, 400, "Bad Request", hdrs=None, fp=None)

        monkeypatch.setattr(lc.urllib.request, "urlopen", bad_request)
        with pytest.raises(RuntimeError):
            make_client(backend="openai").complete("p")
        assert calls["n"] == 1          # 400 is ours: raised at once

    def test_an_unknown_model_says_so_plainly(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 404, "Not Found", hdrs=None, fp=None)

        monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(RuntimeError) as exc:
            make_client(backend="anthropic", model="claude-not-real").complete("p")
        assert "claude-not-real" in str(exc.value)


# ------------------------------------------------------------------ #
# Choosing an engine                                                   #
# ------------------------------------------------------------------ #

class TestBackendSelection:

    def test_a_paid_build_never_falls_back_to_the_stub(self, monkeypatch):
        """The Ollama path degrades to synthetic answers when the server is
        down. A paid backend must not: an operator who asked for Claude and got
        a stub would end up with a knowledge base of invented metrics that
        looks exactly like a real one."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(RuntimeError):
            make_client(backend="anthropic", fallback_to_stub=True)

    def test_ollama_still_falls_back_as_it_always_did(self):
        client = make_client(backend="ollama", base_url="http://localhost:19999",
                             fallback_to_stub=True)
        assert isinstance(client, StubLLMClient)

    def test_stub_wins_over_a_named_provider(self, monkeypatch, tmp_path):
        """`--stub` asks for no model calls at all; naming a provider as well
        must not start charging for them. Note there is no key in the
        environment here: had the provider won, the build would have failed."""
        from config_assessment.plugins.nginx.build_nginx import run_build
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        seen = {}

        def fake_make_client(backend, model, base_url, fallback_to_stub):
            seen["backend"] = backend
            return StubLLMClient()

        monkeypatch.setattr(
            "config_assessment.plugins.nginx.build_nginx.make_client",
            fake_make_client)
        run_build(benchmark_path="/nonexistent.pdf",
                  db_path=str(tmp_path / "t.db"),
                  dry_run=True, stub=True, provider="anthropic")
        assert seen["backend"] == "stub"

    def test_an_ollama_model_tag_is_not_sent_to_a_paid_provider(self, monkeypatch):
        """The CLI's --model default is an Ollama tag. Left untouched while
        switching provider, it would be rejected as an unknown model — so a
        default model means 'this provider's usual one'."""
        from cli.commands.build_cmds import run_build_job
        seen = {}

        def fake_run_build(benchmark_path, db_path, model, ollama_url,
                            dry_run, provider):
            seen["model"] = model
            seen["provider"] = provider
            return 0

        monkeypatch.setattr(
            "config_assessment.plugins.nginx.build_nginx.run_build", fake_run_build)

        run_build_job(benchmark="b.pdf", model=DEFAULT_MODEL["ollama"],
                      ollama_url="", target="nginx", dry_run=True,
                      db_path=":memory:", emit=lambda _: None,
                      provider="anthropic")
        assert seen["model"] == DEFAULT_MODEL["anthropic"]

    def test_an_explicit_model_is_left_alone(self, monkeypatch):
        from cli.commands.build_cmds import run_build_job
        seen = {}

        def fake_run_build(benchmark_path, db_path, model, ollama_url,
                            dry_run, provider):
            seen["model"] = model
            return 0

        monkeypatch.setattr(
            "config_assessment.plugins.nginx.build_nginx.run_build", fake_run_build)

        run_build_job(benchmark="b.pdf", model="claude-opus-4-1", ollama_url="",
                      target="nginx", dry_run=True, db_path=":memory:",
                      emit=lambda _: None, provider="anthropic")
        assert seen["model"] == "claude-opus-4-1"

    def test_an_unknown_provider_is_refused(self):
        from cli.commands.build_cmds import run_build_job
        with pytest.raises(ValueError) as exc:
            run_build_job(benchmark="b.pdf", model="m", ollama_url="",
                          target="nginx", dry_run=True, db_path=":memory:",
                          emit=lambda _: None, provider="gemini")
        assert "gemini" in str(exc.value)

    def test_the_default_provider_is_still_ollama(self, monkeypatch):
        """Every pre-existing caller passes no provider at all; they must keep
        getting the local backend they always got."""
        client = make_client(base_url="http://localhost:19999")
        assert isinstance(client, (StubLLMClient, OllamaClient))
