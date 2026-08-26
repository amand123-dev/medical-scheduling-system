"""
LLM-as-judge grading.

Two things the judge is deliberately NOT asked to do:

1. Decide whether the answer refused. That is a string check on a sentinel the
   answerer emits, not a judgement call — asking a model to classify it adds
   variance to a metric that can be measured exactly.
2. Decide whether the answer is "good". Vague quality scores are where
   LLM-judge harnesses stop being reproducible. The judge answers only two
   narrow, checkable questions: is each claim supported by the passages, and is
   each expected key fact present.

Claim support is graded against the RETRIEVED PASSAGES, not the ground truth. An
answer that states something true about the world but absent from its evidence
is still unsupported — that is exactly the failure mode this metric exists to
catch.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from evals.llm import LLMClient, extract_json

SYSTEM = """You are a strict grader for a retrieval-augmented QA system. You return JSON only.

You will receive the passages that were retrieved, the question, the answer under \
test, and a list of key facts the answer was expected to contain.

Do two things:

1. Break the answer into atomic factual claims. For each, decide whether the \
retrieved passages support it. A claim is supported ONLY if the passages state it \
or directly entail it. A claim that is true in general but absent from the passages \
is UNSUPPORTED. Ignore hedging, citations, and meta-statements like "the passages \
do not say" — these are not claims.

2. For each expected key fact, decide whether the answer conveys it. Match on \
meaning, not wording.

Return exactly this JSON shape and nothing else:
{"claims": [{"claim": "...", "supported": true}],
 "facts": [{"fact": "...", "covered": true}],
 "notes": "one sentence"}"""

USER_TEMPLATE = """Retrieved passages:
{passages}

Question: {question}

Answer under test:
{answer}

Expected key facts:
{facts}"""


@dataclass
class Judgement:
    supported_claims: int = 0
    unsupported_claims: int = 0
    facts_expected: int = 0
    facts_covered: int = 0
    notes: str = ""
    raw: dict = field(default_factory=dict)


def _format_passages(passages: list[dict]) -> str:
    if not passages:
        return "(no passages retrieved)"
    return "\n\n".join(
        f"[source: {p.get('source', '?')}]\n{p.get('content', '')}" for p in passages
    )


def judge_answer(
    client: LLMClient,
    question: str,
    answer: str,
    passages: list[dict],
    key_facts: list[str],
) -> Judgement:
    payload = USER_TEMPLATE.format(
        passages=_format_passages(passages),
        question=question,
        answer=answer,
        facts="\n".join(f"- {f}" for f in key_facts) or "(none)",
    )
    raw = extract_json(client.complete(SYSTEM, payload, max_tokens=1500))

    claims = raw.get("claims") or []
    facts = raw.get("facts") or []
    return Judgement(
        supported_claims=sum(1 for c in claims if c.get("supported")),
        unsupported_claims=sum(1 for c in claims if not c.get("supported")),
        facts_expected=len(facts),
        facts_covered=sum(1 for f in facts if f.get("covered")),
        notes=str(raw.get("notes", ""))[:300],
        raw=raw,
    )
