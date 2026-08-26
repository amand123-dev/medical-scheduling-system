"""
Run the RAG eval.

    python -m evals.run --retrieval-only     # no API key needed
    python -m evals.run                       # full: answer + LLM judge
    python -m evals.run --limit 5 --verbose

Retrieval-only mode grades what retrieval alone can be graded on — whether the
expected sources come back. The full run adds a grounded answerer and an
LLM judge to measure citation accuracy, refusal behaviour and unsupported claims.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings
from app.rag.embeddings import get_embedder
from evals import answerer, judge
from evals.dataset import load_questions, validate
from evals.llm import DEFAULT_MODEL, JUDGE_MODEL, AnthropicClient
from evals.metrics import QuestionResult, summarize
from evals.retrieval_harness import protocol_index, retrieve

REPORT_DIR = Path(__file__).parent / "reports"


@dataclass
class RunConfig:
    k: int = 5
    retrieval_only: bool = False
    limit: int | None = None
    verbose: bool = False
    model: str = DEFAULT_MODEL
    judge_model: str = JUDGE_MODEL
    database_url: str | None = None


async def run_eval(cfg: RunConfig) -> dict:
    questions = load_questions()
    problems = validate(questions)
    if problems:
        raise SystemExit("Dataset is invalid:\n  " + "\n  ".join(problems))
    if cfg.limit:
        questions = questions[: cfg.limit]

    known_sources = {s for q in questions for s in q.expected_sources}
    corpus_sources = {p.name for p in (Path("data") / "protocols").glob("*.md")}
    known_sources |= corpus_sources

    answer_client = None if cfg.retrieval_only else AnthropicClient(cfg.model)
    judge_client = None if cfg.retrieval_only else AnthropicClient(cfg.judge_model)

    results: list[QuestionResult] = []
    async with protocol_index(database_url=cfg.database_url) as session:
        embedder = type(get_embedder(settings.embedding_provider)).__name__
        for q in questions:
            passages = await retrieve(session, q.question, cfg.k)
            r = QuestionResult(
                id=q.id,
                answerable=q.answerable,
                expected_sources=list(q.expected_sources),
                retrieved_sources=list(dict.fromkeys(p["source"] for p in passages)),
                ranked_sources=[p["source"] for p in passages],
                facts_expected=len(q.key_facts),
                tags=list(q.tags),
            )

            if not cfg.retrieval_only:
                ans = answerer.answer_question(answer_client, q.question, passages, known_sources)
                r.answer = ans.text
                r.refused = ans.refused
                r.cited_sources = ans.cited_sources

                verdict = judge.judge_answer(
                    judge_client, q.question, ans.text, passages, q.key_facts
                )
                r.supported_claims = verdict.supported_claims
                r.unsupported_claims = verdict.unsupported_claims
                r.facts_expected = verdict.facts_expected or len(q.key_facts)
                r.facts_covered = verdict.facts_covered
                r.judge_notes = verdict.notes
                r.graded = True

            results.append(r)
            if cfg.verbose:
                mark = "REFUSED" if r.refused else "answered"
                hit = set(r.expected_sources) <= set(r.retrieved_sources)
                print(f"  {q.id:<8} {mark:<9} retrieval_hit={hit}")

    return {
        "run_at": datetime.now(UTC).isoformat(),
        "config": {
            "k": cfg.k,
            "retrieval_only": cfg.retrieval_only,
            "embedder": embedder,
            "embedding_provider": settings.embedding_provider,
            "answer_model": None if cfg.retrieval_only else cfg.model,
            "judge_model": None if cfg.retrieval_only else cfg.judge_model,
        },
        "metrics": summarize(results),
        "results": [r.as_dict() for r in results],
    }


def format_report(report: dict) -> str:
    m = report["metrics"]
    c = report["config"]

    def pct(v):
        return "n/a" if v is None else f"{v * 100:.1f}%"

    lines = [
        "# RAG eval report",
        "",
        f"Run: {report['run_at']}",
        f"Embedder: {c['embedder']} (provider={c['embedding_provider']}), k={c['k']}",
        f"Answer model: {c['answer_model'] or '— retrieval only'}",
        f"Judge model: {c['judge_model'] or '— retrieval only'}",
        "",
        f"{m['n_questions']} questions "
        f"({m['n_answerable']} answerable, {m['n_unanswerable']} unanswerable)",
        "",
        (
            "_Retrieval-only run: answer-level metrics are not measured._\n"
            if c["retrieval_only"]
            else ""
        ),
        "| Metric | Value | Direction |",
        "|---|---|---|",
        f"| Recall@1 | {pct(m['recall_at_1'])} | higher |",
        f"| Recall@3 | {pct(m['recall_at_3'])} | higher |",
        f"| Recall@{c['k']} (all expected sources retrieved) | {pct(m['retrieval_recall'])} | higher |",
        f"| Citation accuracy (cited sources that were correct) | {pct(m['citation_accuracy'])} | higher |",
        f"| Citation coverage (answers citing ≥1 correct source) | {pct(m['citation_coverage'])} | higher |",
        f"| Refusal rate on unanswerable | {pct(m['refusal_rate_on_unanswerable'])} | higher |",
        f"| False refusal rate on answerable | {pct(m['false_refusal_rate_on_answerable'])} | lower |",
        f"| Unsupported claim rate | {pct(m['unsupported_claim_rate'])} | lower |",
        f"| Answer completeness (key facts covered) | {pct(m['answer_completeness'])} | higher |",
        "",
    ]

    missed = [
        r
        for r in report["results"]
        if r["answerable"] and not set(r["expected_sources"]) <= set(r["retrieved_sources"])
    ]
    if missed:
        lines += ["## Retrieval misses", ""]
        for r in missed:
            want = ", ".join(sorted(set(r["expected_sources"]) - set(r["retrieved_sources"])))
            lines.append(f"- `{r['id']}` missing: {want}")
        lines.append("")

    graded = [r for r in report["results"] if r.get("graded")]
    wrong_refusals = [r for r in graded if r["answerable"] and r["refused"]]
    missed_refusals = [r for r in graded if not r["answerable"] and not r["refused"]]
    if wrong_refusals or missed_refusals:
        lines += ["## Refusal errors", ""]
        for r in wrong_refusals:
            lines.append(f"- `{r['id']}` refused an answerable question")
        for r in missed_refusals:
            lines.append(f"- `{r['id']}` answered an unanswerable question instead of refusing")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="Run the RAG eval")
    p.add_argument("--k", type=int, default=5, help="passages retrieved per question")
    p.add_argument(
        "--retrieval-only",
        action="store_true",
        help="skip the LLM answerer and judge; no API key required",
    )
    p.add_argument("--limit", type=int, default=None, help="run only the first N questions")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--judge-model", default=JUDGE_MODEL)
    p.add_argument("--database-url", default=None, help="run against a seeded Postgres instead")
    p.add_argument("--out", default=None, help="write the JSON report here")
    args = p.parse_args()

    if not args.retrieval_only and not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set.\n"
            "Use --retrieval-only to run without an LLM, or export a key."
        )

    cfg = RunConfig(
        k=args.k,
        retrieval_only=args.retrieval_only,
        limit=args.limit,
        verbose=args.verbose,
        model=args.model,
        judge_model=args.judge_model,
        database_url=args.database_url,
    )
    report = asyncio.run(run_eval(cfg))

    REPORT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else REPORT_DIR / f"eval-{stamp}.json"
    out.write_text(json.dumps(report, indent=2))

    print()
    print(format_report(report))
    print(f"JSON report: {out}")


if __name__ == "__main__":
    main()
