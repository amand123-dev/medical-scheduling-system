"""
Metric computation for the RAG eval.

Deliberately pure: these functions take already-collected per-question results
and return numbers. No I/O, no LLM calls, no retrieval. That makes the metric
definitions unit-testable on synthetic results, which matters because a metric
bug looks exactly like a model improvement.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class QuestionResult:
    """One graded question."""

    id: str
    answerable: bool
    expected_sources: list[str]
    retrieved_sources: list[str] = field(default_factory=list)
    ranked_sources: list[str] = field(default_factory=list)
    graded: bool = False
    cited_sources: list[str] = field(default_factory=list)
    refused: bool = False
    supported_claims: int = 0
    unsupported_claims: int = 0
    facts_expected: int = 0
    facts_covered: int = 0
    tags: list[str] = field(default_factory=list)
    answer: str = ""
    judge_notes: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _rate(numerator: int, denominator: int) -> float | None:
    """None, not 0.0, when there is nothing to average — an empty set is not a score of zero."""
    return round(numerator / denominator, 4) if denominator else None


def recall_at_k(results: list[QuestionResult], k: int) -> float | None:
    """Recall using only the top-k retrieved passages.

    Reported at several k because recall at the serving k is not discriminative
    on a small corpus: with five documents and k=5 a system retrieves everything
    and scores 100% without ranking anything correctly. Recall at k=1 and k=3 is
    what actually shows whether ranking works.
    """
    answerable = [r for r in results if r.answerable and r.expected_sources]
    hits = 0
    for r in answerable:
        top = set(r.ranked_sources[:k]) if r.ranked_sources else set(r.retrieved_sources[:k])
        if set(r.expected_sources) <= top:
            hits += 1
    return _rate(hits, len(answerable))


def retrieval_recall(results: list[QuestionResult]) -> float | None:
    """Fraction of answerable questions where every expected source was retrieved.

    Strict by design: partial retrieval on a multi-source question is a miss,
    because an answer built on half the sources is incomplete even when it reads
    fluently.
    """
    answerable = [r for r in results if r.answerable and r.expected_sources]
    hits = sum(1 for r in answerable if set(r.expected_sources) <= set(r.retrieved_sources))
    return _rate(hits, len(answerable))


def citation_accuracy(results: list[QuestionResult]) -> float | None:
    """Of all sources cited across answerable questions, the fraction that were expected.

    This is precision over citations. It penalises padding an answer with
    plausible-looking sources that do not actually contain the fact.
    """
    cited = 0
    correct = 0
    for r in results:
        if not r.answerable or not r.graded:
            continue
        cited += len(r.cited_sources)
        correct += sum(1 for c in r.cited_sources if c in r.expected_sources)
    return _rate(correct, cited)


def citation_coverage(results: list[QuestionResult]) -> float | None:
    """Fraction of answerable questions where at least one correct source was cited.

    Accuracy alone can be gamed by citing a single safe source and omitting the
    rest; coverage is the recall-shaped companion to it.
    """
    answerable = [r for r in results if r.answerable and r.graded]
    hits = sum(1 for r in answerable if set(r.cited_sources) & set(r.expected_sources))
    return _rate(hits, len(answerable))


def refusal_rate(results: list[QuestionResult]) -> float | None:
    """Fraction of UNANSWERABLE questions the system correctly declined. Higher is better."""
    unanswerable = [r for r in results if not r.answerable and r.graded]
    return _rate(sum(1 for r in unanswerable if r.refused), len(unanswerable))


def false_refusal_rate(results: list[QuestionResult]) -> float | None:
    """Fraction of ANSWERABLE questions the system wrongly declined. Lower is better.

    Reported alongside refusal_rate on purpose. Refusal rate in isolation is
    trivially gamed — a system that refuses everything scores 100%. The pair is
    the actual signal.
    """
    answerable = [r for r in results if r.answerable and r.graded]
    return _rate(sum(1 for r in answerable if r.refused), len(answerable))


def unsupported_claim_rate(results: list[QuestionResult]) -> float | None:
    """Fraction of all extracted claims not supported by the retrieved passages.

    Computed over claims, not over questions, so one badly hallucinated answer
    weighs more than one mildly padded answer.
    """
    total = sum(r.supported_claims + r.unsupported_claims for r in results if r.graded)
    unsupported = sum(r.unsupported_claims for r in results if r.graded)
    return _rate(unsupported, total)


def answer_completeness(results: list[QuestionResult]) -> float | None:
    """Fraction of expected key facts present across answerable, non-refused answers."""
    graded = [r for r in results if r.answerable and r.graded and not r.refused]
    expected = sum(r.facts_expected for r in graded)
    covered = sum(r.facts_covered for r in graded)
    return _rate(covered, expected)


def summarize(results: list[QuestionResult]) -> dict:
    """All headline metrics plus the counts needed to interpret them."""
    return {
        "n_questions": len(results),
        "n_answerable": sum(1 for r in results if r.answerable),
        "n_unanswerable": sum(1 for r in results if not r.answerable),
        "n_graded": sum(1 for r in results if r.graded),
        "recall_at_1": recall_at_k(results, 1),
        "recall_at_3": recall_at_k(results, 3),
        "retrieval_recall": retrieval_recall(results),
        "citation_accuracy": citation_accuracy(results),
        "citation_coverage": citation_coverage(results),
        "refusal_rate_on_unanswerable": refusal_rate(results),
        "false_refusal_rate_on_answerable": false_refusal_rate(results),
        "unsupported_claim_rate": unsupported_claim_rate(results),
        "answer_completeness": answer_completeness(results),
    }
