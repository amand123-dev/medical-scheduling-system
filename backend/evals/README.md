# RAG evaluation harness

25 questions with known ground truth over the protocol corpus, graded by an
LLM-as-judge. 17 are answerable from the corpus; 8 are deliberately
unanswerable.

## Run

```bash
python -m evals.run --retrieval-only     # no API key needed
python -m evals.run                      # full: grounded answerer + judge
python -m evals.run --limit 5 --verbose
```

Reports are written to `evals/reports/` as JSON, with a markdown summary printed
to stdout.

## Why the unanswerable questions matter

A RAG system that always produces a confident, well-cited answer looks excellent
on an answerable-only eval and is dangerous in a clinic. The eight unanswerable
items are the ones that catch it. They are not nonsense questions — each is
something a front desk would plausibly ask, where the corpus genuinely has no
answer:

- `un-003` asks how far in advance a patient can book. The scheduler internally
  searches 60 days ahead, so "60 days" is a *plausible* answer that no document
  supports. This is the near-miss trap.
- `un-004` asks for an antibiotic dose — a clinical question against a
  scheduling corpus.
- `un-005` asks how to flag patients doctor-shopping for controlled substances.
  The right answer is that the system does not do this, by design. Inventing a
  procedure here would be a product failure, not just a retrieval failure.

## Metrics

| Metric | Definition | Direction |
|---|---|---|
| `recall_at_1`, `recall_at_3`, `retrieval_recall` | Answerable questions where all expected sources appear in the top-k | higher |
| `citation_accuracy` | Precision over citations: cited sources that were correct | higher |
| `citation_coverage` | Answers citing at least one correct source | higher |
| `refusal_rate_on_unanswerable` | Unanswerable questions correctly declined | higher |
| `false_refusal_rate_on_answerable` | Answerable questions wrongly declined | lower |
| `unsupported_claim_rate` | Claims not supported by retrieved passages, over all claims | lower |
| `answer_completeness` | Expected key facts present in non-refused answers | higher |

Three deliberate choices:

**Refusal rate is never reported alone.** A system that refuses everything
scores 100% on it. `false_refusal_rate` is its companion, and
`test_refuse_everything_is_caught_by_the_pair` pins that down.

**Recall is reported at several k.** With a five-document corpus and k=5,
recall@5 is ~guaranteed and measures nothing. Recall@1 and @3 are what show
whether ranking works.

**Claim support is graded against the retrieved passages, not the ground
truth.** An answer that is true about the world but absent from its evidence is
still unsupported — that is precisely the failure this metric exists to catch.

## What the judge is not asked

Refusal is detected by a sentinel string the answerer emits, not by the judge —
it is exactly measurable, so asking a model adds variance for nothing. The judge
is also never asked whether an answer is "good"; vague quality scores are where
LLM-judge harnesses stop being reproducible. It answers two narrow questions:
is each claim supported by the passages, and is each expected key fact present.

## Baseline

Retrieval-only, fastembed (`BAAI/bge-small-en-v1.5`), k=5:

| Metric | Value |
|---|---|
| Recall@1 | 88.2% |
| Recall@3 | 94.1% |
| Recall@5 | 100.0% |

Answer-level metrics require an API key and are reported as `n/a` in
retrieval-only mode rather than as `0%` — an unmeasured metric must not read as
a failing one.

## Caveats

- The harness ingests the corpus into in-memory SQLite and ranks in Python.
  Production ranks with a pgvector HNSW index, which is approximate, so
  deployed recall can be marginally lower. Pass `--database-url` to measure the
  deployed path exactly.
- 25 questions over 5 documents is a smoke-sized eval. Differences of a few
  percent are noise; it is built to catch regressions and obvious breakage.
- The judge is a single model with no human-agreement calibration. Treat
  `unsupported_claim_rate` as directional.
- Synthetic corpus only. No real patient data is involved at any point.
