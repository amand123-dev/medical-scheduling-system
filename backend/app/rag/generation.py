"""
Grounded answer generation over retrieved passages.

Retrieval on its own makes a person read five cards and synthesise in their
head. This layer does that synthesis, but only from the passages it is handed:
the model is never asked what it knows, only what these passages say.

Two corpora, two different rules, and the difference is deliberate:

  * Protocol documents carry no PHI. Answering over them needs no special
    handling and is enabled by default.
  * Patient passages are PHI even after de-identification -- the token is
    reversible, so this is data minimisation, not anonymisation. Sending them
    to a hosted model is a contractual question (a BAA with zero-retention
    terms), not a technical one. That path is therefore off by default and an
    admin enables it knowingly.

Nothing here decides who may read what. Role gating and identity_access_log
stay in retrieval.py, so this module only ever sees passages a caller was
already entitled to.
"""

from __future__ import annotations

from typing import Protocol

from app.config import settings
from app.rag.retrieval import Passage

GROUNDED_SYSTEM = """You answer questions for clinic staff using ONLY the \
numbered passages provided. These passages are the entire basis for your answer.

Rules:
- Use only what the passages state. Never add clinical knowledge of your own, \
even if you are confident it is correct.
- Cite the passages you used as [1], [2], and so on, inline.
- If the passages do not answer the question, say so plainly and stop. Do not \
speculate, and do not pad the answer with related material that was not asked \
about. "These protocols don't cover that" is a complete and useful answer.
- If the passages conflict, say that they conflict and quote both.
- Be brief. Staff are reading this between patients.
- Never state or imply a diagnosis or a treatment decision. You are surfacing \
what the documents say so a clinician can decide."""

PATIENT_SYSTEM = (
    GROUNDED_SYSTEM
    + """

These passages come from one patient's records. Names have been replaced with a \
[patient:<uuid>] token; refer to the person as "the patient" and never guess at \
a name. Summarise only the care history the passages describe. Do not infer \
risk, adherence, or anything about the patient's character or behaviour."""
)

NO_PASSAGES = "No relevant passages were found, so there is nothing to answer from."


class LLMClient(Protocol):
    """Async completion. A Protocol so tests can drive this with a stub."""

    async def complete(self, system: str, user: str, max_tokens: int) -> str: ...


class AnthropicClient:
    """Thin wrapper over the Anthropic Messages API."""

    def __init__(self, api_key: str, model: str):
        import anthropic

        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        resp = await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()


def get_client() -> LLMClient | None:
    """
    The configured client, or None when no key is set.

    None is a normal state, not an error: the app is useful without generation
    and every deployment of it so far has run that way. Callers fall back to
    returning passages alone.
    """
    if not settings.anthropic_api_key:
        return None
    return AnthropicClient(settings.anthropic_api_key, settings.generation_model)


def build_prompt(question: str, passages: list[Passage]) -> str:
    """Number the passages so the model has something stable to cite."""
    blocks = [f"[{i}] {p.title} ({p.source})\n{p.content}" for i, p in enumerate(passages, start=1)]
    joined = "\n\n".join(blocks)
    return f"Passages:\n\n{joined}\n\n---\n\nQuestion: {question}"


async def answer(
    question: str,
    passages: list[Passage],
    *,
    system: str = GROUNDED_SYSTEM,
    client: LLMClient | None = None,
) -> str | None:
    """
    Generate a grounded answer, or None if generation is unavailable.

    Returning None rather than raising keeps the endpoints degradable: the
    passages are the product, and the answer is a convenience on top of them.
    """
    client = client or get_client()
    if client is None:
        return None
    if not passages:
        # Sending an empty passage list invites the model to answer from its own
        # knowledge, which is the one thing this whole module exists to prevent.
        return NO_PASSAGES
    return await client.complete(
        system, build_prompt(question, passages), settings.generation_max_tokens
    )
