"""
core/llm_client.py
------------------
Abstracção sobre os motores de LLM usados no build: Ollama (local), Anthropic
e OpenAI (pagos), e um stub para testes.

Interface única: LLMClient.complete(prompt, system) -> str

O caller não sabe qual está a ser usado. A escolha é feita uma vez, em
make_client().

CHAVES DE API: lêem-se do ambiente do processo (ANTHROPIC_API_KEY,
OPENAI_API_KEY) e nunca de um argumento, de um pedido HTTP ou de um ficheiro
de configuração. Uma chave que atravesse a API entraria em logs de pedidos,
em `params_json` do job e no browser — três sítios onde não tem como sair
depois. Quem corre o servidor exporta a variável; a consola só diz se está
presente.

Modelos Ollama recomendados para este pipeline (por ordem de preferência):
  - qwen2.5:14b     — melhor raciocínio estruturado, JSON fiável, cabe em 8GB VRAM com Q4
  - llama3.1:8b     — rápido, bom para tarefas simples
  - mistral:7b      — alternativa leve
  - deepseek-r1:8b  — bom raciocínio, verbose

Para CUDA com boa VRAM (16GB+):
  - qwen2.5:32b-instruct-q4_K_M  — melhor qualidade possível localmente
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# The env var each hosted provider reads its key from. One place, so the CLI,
# the API and the console all report the same thing about the same variable.
API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

#: Defaults per provider, used when the caller names a provider but no model.
DEFAULT_MODEL = {
    "ollama": "qwen2.5:14b",
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o",
}


# ------------------------------------------------------------------ #
# Base interface                                                        #
# ------------------------------------------------------------------ #

class LLMClient(ABC):

    @abstractmethod
    def complete(self, prompt: str, system: str = "") -> str:
        """Send a prompt and return the model's text response."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the backend is reachable."""


# ------------------------------------------------------------------ #
# Ollama client (HTTP, zero dependencies)                              #
# ------------------------------------------------------------------ #

class OllamaClient(LLMClient):
    """
    Talks to a local Ollama instance via its REST API.

    Ollama exposes an OpenAI-compatible endpoint at /api/chat.
    Uses only stdlib urllib — no httpx, no requests needed.

    Usage:
        client = OllamaClient(model="qwen2.5:14b")
        response = client.complete(prompt, system)
    """

    def __init__(
        self,
        model: str = "qwen2.5:14b",
        base_url: str = "http://localhost:11434",
        timeout: int = 120,
        temperature: float = 0.1,   # low = more deterministic JSON output
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.temperature = temperature
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def complete(self, prompt: str, system: str = "") -> str:
        """
        Call Ollama /api/chat and return the assistant's message content.
        Retries on connection errors with exponential backoff.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": 1024,
            },
        }).encode("utf-8")

        url = f"{self.base_url}/api/chat"

        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    return body["message"]["content"]

            except urllib.error.HTTPError as e:
                # A 4xx is a permanent client error — retrying is pointless and
                # only hides the cause. The most common one is 404: the server
                # is up but the model isn't pulled.
                if 400 <= e.code < 500:
                    if e.code == 404:
                        raise RuntimeError(
                            f"Ollama returned 404 for model '{self.model}'. The "
                            f"server is running but the model is not installed.\n"
                            f"Pull it:        ollama pull {self.model}\n"
                            f"Or use another: --model <name>  (e.g. one from "
                            f"`ollama list`)"
                        ) from e
                    raise RuntimeError(
                        f"Ollama rejected the request (HTTP {e.code}) for model "
                        f"'{self.model}': {e.reason}"
                    ) from e
                # 5xx — transient server error: fall through to the retry path.
                self._retry_or_raise(e, attempt, wait_label="server error")

            except urllib.error.URLError as e:
                self._retry_or_raise(e, attempt, wait_label="connection error")

    def _retry_or_raise(self, e: Exception, attempt: int, *, wait_label: str) -> None:
        """Back off and retry transient failures; raise a clear error when the
        attempts are exhausted."""
        if attempt < self.max_retries - 1:
            wait = self.retry_delay * (2 ** attempt)
            logger.warning("Ollama request failed (%s, attempt %d/%d): %s — retrying in %.1fs",
                           wait_label, attempt + 1, self.max_retries, e, wait)
            time.sleep(wait)
        else:
            raise RuntimeError(
                f"Ollama unreachable after {self.max_retries} attempts: {e}\n"
                f"Is Ollama running? Try: ollama serve"
            ) from e


# ------------------------------------------------------------------ #
# Hosted clients (Anthropic, OpenAI)                                    #
# ------------------------------------------------------------------ #

class HostedClient(LLMClient):
    """
    A paid, hosted model — Anthropic or OpenAI — over stdlib HTTP.

    The two APIs differ in three details and agree on everything else, so one
    class parameterised by those details beats two near-identical ones. The
    differences: the endpoint, how the system prompt travels (Anthropic takes a
    top-level `system` field, OpenAI a first message with role=system), and
    where the answer sits in the response.

    A hosted build costs real money per rule, so a failure must be loud: unlike
    the Ollama path there is NO fallback to the stub. Silently producing
    synthetic metrics after the operator asked for Claude would poison the
    knowledge base with plausible-looking rules that no model ever wrote.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        *,
        api_key: str,
        timeout: int = 180,
        temperature: float = 0.1,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> None:
        if provider not in API_KEY_ENV:
            raise ValueError(f"Unknown hosted provider: {provider!r}")
        self.provider = provider
        self.model = model
        self._api_key = api_key
        self.timeout = timeout
        self.temperature = temperature
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def is_available(self) -> bool:
        """Whether a key exists — not whether the provider answers.

        Deliberately no network call: a request to check costs a token and
        tells us nothing the first real call would not. What can be checked
        cheaply, and is by far the common failure, is the missing key.
        """
        return bool(self._api_key)

    def _request(self, prompt: str, system: str) -> tuple[str, dict, dict]:
        """(url, headers, payload) for this provider."""
        if self.provider == "anthropic":
            return (
                "https://api.anthropic.com/v1/messages",
                {
                    "content-type": "application/json",
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                },
                {
                    "model": self.model,
                    "max_tokens": 1024,
                    "temperature": self.temperature,
                    **({"system": system} if system else {}),
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return (
            "https://api.openai.com/v1/chat/completions",
            {
                "content-type": "application/json",
                "authorization": f"Bearer {self._api_key}",
            },
            {
                "model": self.model,
                "max_tokens": 1024,
                "temperature": self.temperature,
                "messages": messages,
            },
        )

    def _extract(self, body: dict) -> str:
        if self.provider == "anthropic":
            # content is a list of blocks; the text ones are what we asked for.
            return "".join(
                b.get("text", "") for b in body.get("content", [])
                if b.get("type") == "text"
            )
        return body["choices"][0]["message"]["content"]

    def complete(self, prompt: str, system: str = "") -> str:
        if not self._api_key:
            raise RuntimeError(self.missing_key_message(self.provider))

        url, headers, payload = self._request(prompt, system)
        data = json.dumps(payload).encode("utf-8")

        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(
                    url, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return self._extract(json.loads(resp.read().decode("utf-8")))

            except urllib.error.HTTPError as e:
                # 429 and 529 are the providers asking us to slow down — those
                # are worth retrying. Every other 4xx is our fault and retrying
                # only burns time.
                if e.code in (429, 529):
                    self._retry_or_raise(e, attempt, wait_label="rate limited")
                    continue
                if 400 <= e.code < 500:
                    raise RuntimeError(self._client_error(e)) from e
                self._retry_or_raise(e, attempt, wait_label="server error")

            except urllib.error.URLError as e:
                self._retry_or_raise(e, attempt, wait_label="connection error")

        raise RuntimeError(
            f"{self.provider} unreachable after {self.max_retries} attempts")

    def _client_error(self, e: urllib.error.HTTPError) -> str:
        """A 4xx, said in terms of what the operator has to change.

        The provider's own body is included but never the key, which is why
        this builds the message instead of dumping the request.
        """
        env = API_KEY_ENV[self.provider]
        if e.code in (401, 403):
            return (f"{self.provider} rejected the API key (HTTP {e.code}). "
                    f"Check the value of ${env}.")
        if e.code == 404:
            return (f"{self.provider} does not know the model "
                    f"'{self.model}' (HTTP 404). Check the model name.")
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        return (f"{self.provider} rejected the request (HTTP {e.code}) for "
                f"model '{self.model}'{': ' + detail if detail else ''}")

    def _retry_or_raise(self, e: Exception, attempt: int, *, wait_label: str) -> None:
        if attempt < self.max_retries - 1:
            wait = self.retry_delay * (2 ** attempt)
            logger.warning("%s request failed (%s, attempt %d/%d): %s — retrying in %.1fs",
                           self.provider, wait_label, attempt + 1,
                           self.max_retries, e, wait)
            time.sleep(wait)
        else:
            raise RuntimeError(
                f"{self.provider} unreachable after {self.max_retries} "
                f"attempts: {e}") from e

    @staticmethod
    def missing_key_message(provider: str) -> str:
        env = API_KEY_ENV[provider]
        return (
            f"No API key for {provider}. Export ${env} in the environment that "
            f"runs the build:\n"
            f"    export {env}=...\n"
            f"CVM never accepts the key as an argument or over the API — it "
            f"would end up in logs and in the job record."
        )


def api_key_present(provider: str) -> bool:
    """Whether the process environment carries a key for this provider.

    The only thing about a key that is safe to report anywhere — the console
    calls this through GET /builds/providers so an operator can tell a missing
    key from a wrong model name before spending an hour finding out.
    """
    env = API_KEY_ENV.get(provider)
    return bool(env and os.environ.get(env, "").strip())


# ------------------------------------------------------------------ #
# Stub client (testes e modo offline)                                   #
# ------------------------------------------------------------------ #

class StubLLMClient(LLMClient):
    """
    Devolve respostas pré-definidas ou um JSON mínimo válido.
    Usado em testes e quando o Ollama não está disponível.
    """

    def __init__(self, fixed_response: Optional[str] = None) -> None:
        self._fixed = fixed_response

    def is_available(self) -> bool:
        return True

    def complete(self, prompt: str, system: str = "") -> str:
        if self._fixed:
            return self._fixed
        # Minimal valid CCSS metric JSON so the pipeline doesn't break
        return json.dumps({
            "ac": "L",
            "c": "P",
            "i": "N",
            "a": "N",
            "gel": "M",
            "grl": "H",
            "justification": "Stub response — Ollama not available.",
            "recommendation": "Configure this directive according to CIS Benchmark guidance.",
            "cve_ids": [],
        })


# ------------------------------------------------------------------ #
# Factory                                                              #
# ------------------------------------------------------------------ #

def make_client(
    backend: str = "ollama",
    model: str = "qwen2.5:14b",
    base_url: str = "http://localhost:11434",
    fallback_to_stub: bool = True,
) -> LLMClient:
    """
    Build an LLMClient.

    If backend='ollama' and Ollama is unreachable, falls back to StubLLMClient
    when fallback_to_stub=True (useful for development without GPU). The hosted
    backends never fall back: see HostedClient.

    Args:
        backend:          'ollama', 'anthropic', 'openai' or 'stub'
        model:            model name; falls back to DEFAULT_MODEL[backend]
        base_url:         Ollama server URL (ignored by the hosted backends)
        fallback_to_stub: If True, returns StubLLMClient when Ollama is down
    """
    if backend == "stub":
        logger.info("LLM backend: stub (no model calls)")
        return StubLLMClient()

    if backend in API_KEY_ENV:
        api_key = os.environ.get(API_KEY_ENV[backend], "").strip()
        if not api_key:
            # Refused here rather than at the first call: a build that dies an
            # hour in, having already written half a knowledge base, is a worse
            # way to learn the key is missing.
            raise RuntimeError(HostedClient.missing_key_message(backend))
        chosen = model or DEFAULT_MODEL[backend]
        logger.info("LLM backend: %s model=%s", backend, chosen)
        return HostedClient(backend, chosen, api_key=api_key)

    client = OllamaClient(model=model, base_url=base_url)

    if not client.is_available():
        msg = f"Ollama not reachable at {base_url}"
        if fallback_to_stub:
            logger.warning("%s — falling back to stub client", msg)
            return StubLLMClient()
        raise RuntimeError(
            f"{msg}\n"
            "Start Ollama with: ollama serve\n"
            f"Pull the model with: ollama pull {model}"
        )

    logger.info("LLM backend: Ollama model=%s at %s", model, base_url)
    return client
