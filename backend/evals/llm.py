"""
LLM access for the eval harness.

Behind a Protocol so the answerer and the judge can be driven by a stub in
tests. The suite must never need an API key or a network call.
"""

from __future__ import annotations

import json
import os
import re
from typing import Protocol

DEFAULT_MODEL = "claude-sonnet-5"
JUDGE_MODEL = "claude-sonnet-5"


class LLMClient(Protocol):
    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str: ...


class AnthropicClient:
    """Thin wrapper over the Anthropic Messages API."""

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None):
        import anthropic

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Run with --retrieval-only to compute "
                "retrieval metrics without an LLM, or export a key."
            )
        self.model = model
        self._client = anthropic.Anthropic(api_key=key)

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in resp.content if block.type == "text")


class ScriptedClient:
    """Test double. Returns queued responses in order."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        self.calls.append((system, user))
        if not self._responses:
            raise AssertionError("ScriptedClient ran out of responses")
        return self._responses.pop(0)


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model response.

    Models wrap JSON in prose or fences often enough that requiring a bare
    object makes the harness flaky for reasons unrelated to what it measures.
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in response: {text[:200]!r}")
    depth = 0
    in_string = False
    escaped = False
    for i, ch in enumerate(text[start:], start):
        if in_string:
            # Braces inside string values must not move the depth counter, or a
            # judge rationale containing "}" truncates the object.
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError(f"unterminated JSON object in response: {text[:200]!r}")
