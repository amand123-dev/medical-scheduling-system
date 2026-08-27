"""Load and validate the eval question set."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DATASET_PATH = Path(__file__).parent / "questions.json"
CORPUS_DIR = Path(__file__).resolve().parent.parent / "data" / "protocols"


@dataclass(frozen=True)
class EvalQuestion:
    id: str
    question: str
    answerable: bool
    expected_sources: list[str]
    ground_truth: str
    key_facts: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def load_questions(path: Path | None = None) -> list[EvalQuestion]:
    data = json.loads((path or DATASET_PATH).read_text())
    return [EvalQuestion(**q) for q in data["questions"]]


def validate(questions: list[EvalQuestion], corpus_dir: Path | None = None) -> list[str]:
    """Return a list of dataset problems. Empty means the dataset is sound."""
    corpus = corpus_dir or CORPUS_DIR
    available = {p.name for p in corpus.glob("*.md")} if corpus.exists() else set()
    problems: list[str] = []

    seen: set[str] = set()
    for q in questions:
        if q.id in seen:
            problems.append(f"{q.id}: duplicate id")
        seen.add(q.id)

        if not q.question.strip():
            problems.append(f"{q.id}: empty question")
        if not q.ground_truth.strip():
            problems.append(f"{q.id}: empty ground_truth")

        if q.answerable:
            if not q.expected_sources:
                problems.append(f"{q.id}: answerable but names no expected source")
            if not q.key_facts:
                problems.append(f"{q.id}: answerable but lists no key_facts to grade against")
        else:
            if q.expected_sources:
                problems.append(f"{q.id}: unanswerable but names expected sources")
            if q.key_facts:
                problems.append(f"{q.id}: unanswerable but lists key_facts")

        for src in q.expected_sources:
            if available and src not in available:
                problems.append(f"{q.id}: expected source {src!r} is not in the corpus")

    return problems
