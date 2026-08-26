"""
The system under test: answer a question from retrieved passages only.

This is intentionally a strict grounded-QA prompt rather than a helpful
assistant. The eval measures whether the retrieval layer plus a disciplined
prompt can stay inside its evidence, so the prompt has to make refusal a
first-class option — otherwise the unanswerable items measure nothing but the
model's willingness to guess.
"""

from __future__ import annotations

from dataclasses import dataclass

from evals.llm import LLMClient

REFUSAL_MARKER = "INSUFFICIENT_CONTEXT"

SYSTEM = f"""You answer questions about a medical practice's scheduling protocols \
using ONLY the passages provided.

Rules:
- Use only the passages. Do not use general knowledge about medical practices.
- If the passages do not contain the answer, reply with exactly {REFUSAL_MARKER} \
followed by one sentence saying what is missing. Do not guess a plausible answer.
- Cite the source document for each claim, inline, as [source: filename].
- Do not answer clinical questions (diagnosis, treatment, dosing). These protocols \
cover scheduling only; reply {REFUSAL_MARKER} and say it is a clinical question.
- Be concise. No preamble."""

USER_TEMPLATE = """Passages:
{passages}

Question: {question}"""


@dataclass
class Answer:
    text: str
    refused: bool
    cited_sources: list[str]


def _format_passages(passages: list[dict]) -> str:
    if not passages:
        return "(no passages retrieved)"
    return "\n\n".join(
        f"[source: {p.get('source', '?')}]\n{p.get('content', '')}" for p in passages
    )


def extract_citations(text: str, known_sources: set[str] | None = None) -> list[str]:
    """Pull [source: x] citations out of an answer, de-duplicated, in order."""
    import re

    found: list[str] = []
    for match in re.finditer(r"\[source:\s*([^\]]+)\]", text, re.IGNORECASE):
        name = match.group(1).strip()
        if known_sources is not None and name not in known_sources:
            continue
        if name not in found:
            found.append(name)
    return found


def answer_question(
    client: LLMClient,
    question: str,
    passages: list[dict],
    known_sources: set[str] | None = None,
) -> Answer:
    text = client.complete(
        SYSTEM,
        USER_TEMPLATE.format(passages=_format_passages(passages), question=question),
        max_tokens=700,
    ).strip()
    return Answer(
        text=text,
        refused=REFUSAL_MARKER in text.upper(),
        cited_sources=extract_citations(text, known_sources),
    )
