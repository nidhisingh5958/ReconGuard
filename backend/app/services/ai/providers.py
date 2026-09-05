"""Model provider adapters.

Kept deliberately thin. The provider's only job is: take a system prompt and a
user prompt, return parsed JSON. It knows nothing about reconciliation, and no
provider is ever handed anything the caller has not already bounded.

Providers are optional. If none is reachable the arbitration layer falls back to
the deterministic arbitrator, so the absence of a key is a degraded feature and
never an outage.

Requests use ``httpx`` directly rather than a vendor SDK: one small HTTP call
per residual, no streaming, no tool use. A dependency that pulls in a client
library for this would cost more than it saves.
"""

from __future__ import annotations

import abc
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_TOKENS = 1024

#: Current Claude model ids. Sonnet is the default: this is a short, highly
#: structured extraction task against pre-retrieved evidence, not open-ended
#: reasoning, so the largest model buys nothing here.
ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-5"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"


class ProviderError(RuntimeError):
    """Raised when a provider cannot be constructed or a call fails."""


@dataclass(slots=True)
class ProviderResponse:
    payload: Dict[str, Any]
    raw_text: str
    model: str
    provider: str


class LLMProvider(abc.ABC):
    """Return parsed JSON for a system + user prompt pair."""

    name = "abstract"
    model = ""

    @abc.abstractmethod
    def complete_json(self, system: str, user: str) -> ProviderResponse:
        """Call the model and return its JSON object."""


def extract_json(text: str) -> Dict[str, Any]:
    """Pull the first JSON object out of a model response.

    Models wrap JSON in prose or fences often enough that failing on it would
    make the integration brittle for no benefit. What we do NOT do is repair
    malformed JSON: a response we cannot parse cleanly is an error, and the
    caller falls back rather than guessing at intent.
    """
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", stripped, re.DOTALL)
    if fenced:
        stripped = fenced.group(1).strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ProviderError(f"response contained no JSON object: {text[:200]!r}")
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ProviderError(f"could not parse JSON from response: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ProviderError("expected a JSON object at the top level")
    return parsed


class AnthropicProvider(LLMProvider):
    """Anthropic Messages API."""

    name = "anthropic"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = ANTHROPIC_DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        base_url: str = "https://api.anthropic.com/v1/messages",
    ) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")
        self.model = model
        self.timeout = timeout
        self.base_url = base_url

    def complete_json(self, system: str, user: str) -> ProviderResponse:
        import httpx

        body = {
            "model": self.model,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        try:
            response = httpx.post(
                self.base_url,
                json=body,
                timeout=self.timeout,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # network, auth, rate limit, malformed
            raise ProviderError(f"anthropic request failed: {exc}") from exc

        blocks: List[Dict[str, Any]] = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return ProviderResponse(
            payload=extract_json(text),
            raw_text=text,
            model=data.get("model", self.model),
            provider=self.name,
        )


class OpenAIProvider(LLMProvider):
    """OpenAI Chat Completions API."""

    name = "openai"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = OPENAI_DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        base_url: str = "https://api.openai.com/v1/chat/completions",
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        if not self.api_key:
            raise ProviderError("OPENAI_API_KEY is not set")
        self.model = model
        self.timeout = timeout
        self.base_url = base_url

    def complete_json(self, system: str, user: str) -> ProviderResponse:
        import httpx

        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            response = httpx.post(
                self.base_url,
                json=body,
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "content-type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise ProviderError(f"openai request failed: {exc}") from exc

        text = data["choices"][0]["message"]["content"]
        return ProviderResponse(
            payload=extract_json(text),
            raw_text=text,
            model=data.get("model", self.model),
            provider=self.name,
        )


class ScriptedProvider(LLMProvider):
    """A provider that replays canned responses. For tests only.

    Lets the full LLM arbitration path, including the verification gate, be
    exercised without a network or a key. That matters: the gate is the part
    most worth testing, and it should be tested against hostile responses.
    """

    name = "scripted"

    def __init__(self, responses: List[Any], model: str = "scripted-1") -> None:
        self.responses = list(responses)
        self.model = model
        self.calls: List[Dict[str, str]] = []

    def complete_json(self, system: str, user: str) -> ProviderResponse:
        self.calls.append({"system": system, "user": user})
        if not self.responses:
            raise ProviderError("scripted provider exhausted")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        text = item if isinstance(item, str) else json.dumps(item)
        return ProviderResponse(
            payload=extract_json(text),
            raw_text=text,
            model=self.model,
            provider=self.name,
        )


def build_provider(name: str, **kwargs: Any) -> LLMProvider:
    """Construct a provider by name. Raises ProviderError if unavailable."""
    normalised = (name or "").strip().lower()
    if normalised in ("anthropic", "claude"):
        return AnthropicProvider(**kwargs)
    if normalised in ("openai", "gpt"):
        return OpenAIProvider(**kwargs)
    raise ProviderError(f"unknown model provider {name!r}")
