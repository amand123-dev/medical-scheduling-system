"""
Guards on the synthetic patient-document corpus.

These documents are what patient RAG retrieves and what any summarisation is
grounded in, so incoherent source data surfaces as an incoherent answer. That
is not hypothetical: the missed-appointment note was originally formatted from
the same values as the visit summary, so a quarter of patients had one document
saying they attended a visit and another saying they did not attend the same
one, and the production summariser flagged the contradiction on the first run.
"""

from __future__ import annotations

import importlib.util
import random
import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "seed_patient_documents.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("seed_patient_documents", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def seeder():
    return _load_module()


def _by_type(docs) -> dict[str, str]:
    return {doc_type: text for _suffix, doc_type, text in docs}


def _date_in(text: str) -> str | None:
    """The '## What happened' paragraph names the appointment date."""
    m = re.search(r"on ([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    return m.group(1) if m else None


def _scheduled_date_in(text: str) -> str | None:
    m = re.search(r"scheduled for ([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    return m.group(1) if m else None


class TestDocumentsAreInternallyConsistent:
    def test_attended_and_missed_are_never_the_same_appointment(self, seeder):
        """
        A chart may contain both an attended visit and a missed one, but they
        must be different appointments. Same date + same provider + opposite
        outcome is a flat contradiction.
        """
        random.seed(20260827)
        checked = 0
        for _ in range(400):
            docs = _by_type(seeder.build_documents("Jane", "Doe"))
            if "missed_appointment" not in docs:
                continue
            checked += 1
            visit_date = _date_in(docs["visit_summary"])
            missed_date = _scheduled_date_in(docs["missed_appointment"])
            assert visit_date and missed_date
            assert visit_date != missed_date, (
                f"visit summary and missed-appointment note describe the same "
                f"appointment on {visit_date}: one says attended, one says missed"
            )
        assert checked > 20, "the missed-appointment branch barely fired; test proves little"

    def test_missed_appointment_precedes_the_summarised_visit(self, seeder):
        """Ordering keeps the chart readable as a sequence rather than a jumble."""
        from datetime import datetime

        random.seed(11)
        for _ in range(200):
            docs = _by_type(seeder.build_documents("Jane", "Doe"))
            if "missed_appointment" not in docs:
                continue
            visit = datetime.strptime(_date_in(docs["visit_summary"]), "%B %d, %Y")
            missed = datetime.strptime(_scheduled_date_in(docs["missed_appointment"]), "%B %d, %Y")
            assert missed < visit


class TestDocumentsRespectProjectConstraints:
    """CLAUDE.md: no clinical surveillance, and signals support rather than punish."""

    def test_no_clinical_or_surveillance_content(self, seeder):
        """
        The ban is on clinical surveillance and clinical decisions, not on
        ordinary pre-visit logistics. "Bring a list of your current
        prescriptions to your intake appointment" is instructions given TO a
        patient; it is not medication tracking, so it stays.
        """
        banned = (
            "diagnos",
            "opioid",
            "dosage",
            "controlled substance",
            "doctor shopping",
            "doctor-shopping",
            "flagged as",
            "risk of abuse",
        )
        random.seed(7)
        for _ in range(120):
            for _suffix, _doc_type, text in seeder.build_documents("Jane", "Doe"):
                lowered = text.lower()
                for term in banned:
                    assert term not in lowered, f"clinical content leaked in: {term!r}"

    def test_missed_appointments_record_a_cause_not_a_judgement(self, seeder):
        """A no-show is a logistics problem to solve, never evidence about the person."""
        judgemental = ("noncompliant", "non-compliant", "unreliable", "repeat offender", "frequent")
        random.seed(3)
        for _ in range(300):
            docs = _by_type(seeder.build_documents("Jane", "Doe"))
            note = docs.get("missed_appointment")
            if not note:
                continue
            lowered = note.lower()
            for term in judgemental:
                assert term not in lowered
            assert "## Reason recorded" in note
            assert "## Outreach" in note, (
                "a missed appointment must record outreach, not just a miss"
            )
