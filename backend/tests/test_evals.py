"""
Tests for the eval harness.

An eval harness that is itself wrong is worse than no eval, because it reports
confident numbers. These tests cover the two failure modes that matter: the
dataset drifting out of sync with the corpus, and the metric definitions being
subtly wrong. Both run fully offline — the LLM layer is driven by a scripted
double, so no API key and no network are involved.
"""

from __future__ import annotations

import pytest

from evals import answerer, judge
from evals.dataset import load_questions, validate
from evals.llm import ScriptedClient, extract_json
from evals.metrics import (
    QuestionResult,
    answer_completeness,
    citation_accuracy,
    citation_coverage,
    false_refusal_rate,
    recall_at_k,
    refusal_rate,
    summarize,
    unsupported_claim_rate,
)


class TestDataset:
    def test_dataset_is_valid(self):
        assert validate(load_questions()) == []

    def test_has_enough_questions(self):
        assert len(load_questions()) >= 25

    def test_has_unanswerable_questions(self):
        """The unanswerable items are the point; without them refusal is unmeasurable."""
        unanswerable = [q for q in load_questions() if not q.answerable]
        assert len(unanswerable) >= 5

    def test_every_expected_source_exists_in_the_corpus(self):
        """Catches a doc being renamed out from under the dataset."""
        assert validate(load_questions()) == []

    def test_safety_constraints_are_probed(self):
        """CLAUDE.md's hard constraints should be represented in the eval set."""
        tags = {t for q in load_questions() for t in q.tags}
        assert "safety" in tags

    def test_no_real_pii_in_questions(self):
        for q in load_questions():
            assert "@" not in q.question, f"{q.id} looks like it contains an email"


class TestMetrics:
    def test_recall_at_k_respects_rank(self):
        r = QuestionResult(
            id="a",
            answerable=True,
            expected_sources=["b.md"],
            ranked_sources=["a.md", "b.md", "c.md"],
        )
        assert recall_at_k([r], 1) == 0.0
        assert recall_at_k([r], 2) == 1.0

    def test_recall_requires_all_expected_sources(self):
        """Partial retrieval on a multi-source question is a miss, not a half-hit."""
        r = QuestionResult(
            id="a",
            answerable=True,
            expected_sources=["a.md", "b.md"],
            ranked_sources=["a.md", "c.md"],
        )
        assert recall_at_k([r], 5) == 0.0

    def test_citation_accuracy_is_precision_over_citations(self):
        r = QuestionResult(
            id="a",
            answerable=True,
            expected_sources=["a.md"],
            cited_sources=["a.md", "wrong.md"],
            graded=True,
        )
        assert citation_accuracy([r]) == 0.5

    def test_citation_coverage_is_per_question(self):
        r = QuestionResult(
            id="a",
            answerable=True,
            expected_sources=["a.md"],
            cited_sources=["a.md", "wrong.md"],
            graded=True,
        )
        assert citation_coverage([r]) == 1.0

    def test_refusal_rate_counts_only_unanswerable(self):
        results = [
            QuestionResult(
                id="u1", answerable=False, expected_sources=[], refused=True, graded=True
            ),
            QuestionResult(
                id="u2", answerable=False, expected_sources=[], refused=False, graded=True
            ),
            QuestionResult(
                id="a1", answerable=True, expected_sources=["a.md"], refused=True, graded=True
            ),
        ]
        assert refusal_rate(results) == 0.5

    def test_false_refusal_rate_counts_only_answerable(self):
        results = [
            QuestionResult(
                id="u1", answerable=False, expected_sources=[], refused=True, graded=True
            ),
            QuestionResult(
                id="a1", answerable=True, expected_sources=["a.md"], refused=True, graded=True
            ),
            QuestionResult(
                id="a2", answerable=True, expected_sources=["a.md"], refused=False, graded=True
            ),
        ]
        assert false_refusal_rate(results) == 0.5

    def test_refuse_everything_is_caught_by_the_pair(self):
        """A system that refuses everything scores perfectly on refusal_rate alone.

        This is why false_refusal_rate is reported next to it.
        """
        results = [
            QuestionResult(
                id=f"u{i}", answerable=False, expected_sources=[], refused=True, graded=True
            )
            for i in range(4)
        ] + [
            QuestionResult(
                id=f"a{i}", answerable=True, expected_sources=["a.md"], refused=True, graded=True
            )
            for i in range(4)
        ]
        assert refusal_rate(results) == 1.0
        assert false_refusal_rate(results) == 1.0

    def test_unsupported_claim_rate_is_over_claims_not_questions(self):
        results = [
            QuestionResult(
                id="a",
                answerable=True,
                expected_sources=[],
                supported_claims=1,
                unsupported_claims=3,
                graded=True,
            ),
            QuestionResult(
                id="b",
                answerable=True,
                expected_sources=[],
                supported_claims=6,
                unsupported_claims=0,
                graded=True,
            ),
        ]
        assert unsupported_claim_rate(results) == 0.3

    def test_completeness_ignores_refused_answers(self):
        results = [
            QuestionResult(
                id="a",
                answerable=True,
                expected_sources=[],
                refused=True,
                facts_expected=3,
                facts_covered=0,
                graded=True,
            ),
            QuestionResult(
                id="b",
                answerable=True,
                expected_sources=[],
                facts_expected=2,
                facts_covered=1,
                graded=True,
            ),
        ]
        assert answer_completeness(results) == 0.5

    def test_empty_denominator_is_none_not_zero(self):
        """An unmeasured metric must not report as a perfect zero or a failing zero."""
        r = QuestionResult(id="a", answerable=True, expected_sources=["a.md"])
        assert citation_accuracy([r]) is None
        assert refusal_rate([r]) is None

    def test_ungraded_results_are_excluded(self):
        """Retrieval-only runs must not report answer-level metrics."""
        results = [
            QuestionResult(id="u", answerable=False, expected_sources=[], refused=False),
            QuestionResult(id="a", answerable=True, expected_sources=["a.md"]),
        ]
        m = summarize(results)
        assert m["refusal_rate_on_unanswerable"] is None
        assert m["citation_accuracy"] is None
        assert m["n_graded"] == 0


class TestAnswerer:
    def test_detects_refusal_sentinel(self):
        client = ScriptedClient([f"{answerer.REFUSAL_MARKER} the passages say nothing about fees."])
        a = answerer.answer_question(client, "What is the fee?", [])
        assert a.refused is True

    def test_normal_answer_is_not_a_refusal(self):
        client = ScriptedClient(["It is 40 minutes [source: visit-types-and-durations.md]."])
        a = answerer.answer_question(client, "How long?", [])
        assert a.refused is False
        assert a.cited_sources == ["visit-types-and-durations.md"]

    def test_citations_are_deduplicated_in_order(self):
        text = "x [source: b.md] y [source: a.md] z [source: b.md]"
        assert answerer.extract_citations(text) == ["b.md", "a.md"]

    def test_hallucinated_citations_are_dropped_when_sources_are_known(self):
        """A model citing a document that does not exist must not score as a citation."""
        text = "x [source: made-up.md] y [source: a.md]"
        assert answerer.extract_citations(text, known_sources={"a.md"}) == ["a.md"]

    def test_passages_are_labelled_with_their_source(self):
        client = ScriptedClient(["ok"])
        answerer.answer_question(client, "q", [{"source": "a.md", "content": "hello"}])
        _system, user = client.calls[0]
        assert "[source: a.md]" in user and "hello" in user


class TestJudge:
    def test_counts_supported_and_unsupported_claims(self):
        client = ScriptedClient(
            [
                '{"claims": [{"claim": "x", "supported": true},'
                ' {"claim": "y", "supported": false}],'
                ' "facts": [{"fact": "f", "covered": true}], "notes": "ok"}'
            ]
        )
        v = judge.judge_answer(client, "q", "a", [], ["f"])
        assert (v.supported_claims, v.unsupported_claims) == (1, 1)
        assert (v.facts_expected, v.facts_covered) == (1, 1)

    def test_tolerates_fenced_json(self):
        client = ScriptedClient(['```json\n{"claims": [], "facts": [], "notes": "n"}\n```'])
        v = judge.judge_answer(client, "q", "a", [], [])
        assert v.notes == "n"

    def test_tolerates_braces_inside_strings(self):
        client = ScriptedClient(['{"claims": [], "facts": [], "notes": "used {curly} braces"}'])
        v = judge.judge_answer(client, "q", "a", [], [])
        assert v.notes == "used {curly} braces"

    def test_judge_sees_passages_not_ground_truth(self):
        """Claims are graded against retrieved evidence, not against the answer key."""
        client = ScriptedClient(['{"claims": [], "facts": [], "notes": ""}'])
        judge.judge_answer(client, "q", "a", [{"source": "s.md", "content": "EVIDENCE"}], [])
        _system, user = client.calls[0]
        assert "EVIDENCE" in user

    def test_malformed_response_raises(self):
        client = ScriptedClient(["not json at all"])
        with pytest.raises(ValueError):
            judge.judge_answer(client, "q", "a", [], [])


class TestJsonExtraction:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ('{"a": 1}', {"a": 1}),
            ('prose {"a": 1} more', {"a": 1}),
            ('```json\n{"a": 1}\n```', {"a": 1}),
            ('{"a": "brace } inside"}', {"a": "brace } inside"}),
            (r'{"a": "quote \" and } brace"}', {"a": 'quote " and } brace'}),
        ],
    )
    def test_extracts(self, raw, expected):
        assert extract_json(raw) == expected
