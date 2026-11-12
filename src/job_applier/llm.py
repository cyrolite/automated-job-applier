"""Pluggable LLM client.

Providers:
  anthropic — Claude via the official SDK (needs ANTHROPIC_API_KEY)
  ollama    — a local model over HTTP, no API key, no data leaves the machine
  none      — generation disabled; scoring and gap reports still work

Nothing else in the codebase talks to a model directly, so swapping providers
is a one-line change in .env.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import settings


class LLMUnavailable(RuntimeError):
    """Raised when generation is requested but no provider is configured."""


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str


# ----------------------------------------------------------------------
class BaseClient:
    provider = "base"

    def __init__(self, model: str | None = None, max_tokens: int | None = None):
        self.model = model or settings.model
        self.max_tokens = max_tokens or settings.max_tokens

    def complete(self, system: str, user: str) -> LLMResponse:  # pragma: no cover
        raise NotImplementedError

    def complete_json(self, system: str, user: str, retries: int = 2) -> dict:
        """Complete and parse a JSON object, retrying once with a nudge."""
        last_err: Exception | None = None
        prompt = user
        for attempt in range(retries + 1):
            resp = self.complete(system, prompt)
            try:
                return extract_json(resp.text)
            except ValueError as e:
                last_err = e
                prompt = (
                    user
                    + "\n\nYour previous reply could not be parsed as JSON. "
                      "Reply with a single valid JSON object and nothing else — "
                      "no prose, no code fences."
                )
        raise ValueError(f"Model did not return parseable JSON: {last_err}")


class AnthropicClient(BaseClient):
    provider = "anthropic"

    def __init__(self, **kw):
        super().__init__(**kw)
        if not settings.anthropic_api_key:
            raise LLMUnavailable(
                "ANTHROPIC_API_KEY is not set. Add it to .env, or set "
                "JA_PROVIDER=ollama to run a local model instead."
            )
        try:
            import anthropic  # noqa: F401
        except ImportError as e:
            raise LLMUnavailable(
                "The 'anthropic' package is not installed. Run: pip install anthropic"
            ) from e
        import anthropic

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def complete(self, system: str, user: str) -> LLMResponse:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in msg.content if block.type == "text")
        return LLMResponse(text=text, provider=self.provider, model=self.model)


class OllamaClient(BaseClient):
    """Local inference. Useful because nothing about your job search leaves
    the machine, and it costs nothing to run."""

    provider = "ollama"

    def __init__(self, **kw):
        super().__init__(**kw)
        if self.model.startswith("claude"):
            self.model = "mistral"   # sane local default

    def complete(self, system: str, user: str) -> LLMResponse:
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": user,
                "system": system,
                "stream": False,
                "options": {"num_predict": self.max_tokens, "temperature": 0.3},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{settings.ollama_host.rstrip('/')}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise LLMUnavailable(
                f"Could not reach Ollama at {settings.ollama_host}. "
                "Is it running? Try: ollama serve"
            ) from e
        return LLMResponse(text=data.get("response", ""), provider=self.provider, model=self.model)


class NullClient(BaseClient):
    provider = "none"

    def complete(self, system: str, user: str) -> LLMResponse:
        raise LLMUnavailable(
            "No LLM provider configured (JA_PROVIDER=none). "
            "Scoring and gap reports still work; document generation needs a provider."
        )


# ----------------------------------------------------------------------
def get_client(provider: str | None = None, **kw) -> BaseClient:
    name = (provider or settings.provider or "none").lower()
    if name == "anthropic":
        return AnthropicClient(**kw)
    if name == "ollama":
        return OllamaClient(**kw)
    if name == "none":
        return NullClient(**kw)
    raise ValueError(f"Unknown provider: {name!r} (use anthropic, ollama or none)")


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict:
    """Pull a JSON object out of a reply, tolerating code fences and stray prose."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty response")

    candidates: list[str] = []
    for m in _FENCE.finditer(text):
        candidates.append(m.group(1).strip())
    candidates.append(text)
    # Outermost braces as a last resort.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for c in candidates:
        try:
            parsed = json.loads(c)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON object found in response")
