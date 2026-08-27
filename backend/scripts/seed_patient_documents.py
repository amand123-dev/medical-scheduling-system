"""Generate and ingest a synthetic patient-document corpus.

The protocol corpus (data/protocols/*.md) is practice-wide and contains no PHI.
This script fills the other half: per-patient documents that live in
`identity.patient_document_chunk`, so that /rag/patients/{uuid}/context and the
`get_patient_context` MCP tool return passages instead of an empty list.

Two things this deliberately does the long way round:

1. Documents are written WITH the patient's real name, then put through
   `chunking.deidentify` against that patient's identity record before ingest.
   Generating pre-scrubbed text would be easier and would prove nothing; this
   way the de-identification step is actually exercised, and the script fails
   loudly if a name survives it.

2. Content is scheduling and care-coordination only -- what the visit needs,
   when the follow-up is due, what prep was sent, why a slot was missed. There
   are no diagnoses, no medications, and no behavioural flags. A no-show is
   recorded as a scheduling fact with a logistical reason, never as a judgement
   about the patient.

Run from backend/:  python scripts/seed_patient_documents.py
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402
from app.identity.models import PatientIdentity  # noqa: E402
from app.rag.chunking import deidentify  # noqa: E402
from app.rag.ingest import ingest_patient_document  # noqa: E402
from app.rag.models import PatientDocumentChunk  # noqa: E402

# ── Document templates ────────────────────────────────────────────────────────
# Written as a front-desk or care-coordinator would write them: what happened at
# the visit from a scheduling standpoint, and what needs to happen next.

VISIT_SUMMARY = """# Visit Summary — {visit_type}

## What happened

{first} {last} attended a {visit_type_lower} on {date} with {provider}. The
appointment ran {duration} minutes, which is the standard length for this visit
type. {arrival}

## Scheduling notes

{scheduling_note}

## Next steps

{next_step}
"""

PREP_NOTE = """# Preparation Instructions Sent — {visit_type}

## Sent to patient

Preparation instructions for the {visit_type_lower} were sent to {first} {last}
{lead_time} before the appointment, following the standard prep protocol for
this visit type.

## Instructions given

{instructions}

## Confirmation

{confirmation}
"""

FOLLOWUP_NOTE = """# Follow-Up Scheduling — {visit_type}

## Required window

The {visit_type_lower} on {date} requires a follow-up within {window} days per
the follow-up protocol. For {first} {last} this puts the due date at {due_date}.

## Status

{status}

## Coordination notes

{coordination}
"""

MISSED_NOTE = """# Missed Appointment — {visit_type}

## What happened

{first} {last} did not attend the {visit_type_lower} scheduled for {date} with
{provider}. The slot was released and offered to the waitlist.

## Reason recorded

{reason}

## Outreach

{outreach}
"""

ARRIVALS = [
    "The patient arrived on time and check-in was routine.",
    "The patient arrived about ten minutes late; the visit still finished within its slot.",
    "Check-in was completed online ahead of the visit, so no front-desk time was needed.",
    "The patient arrived early and was seen at the scheduled time.",
]

SCHEDULING_NOTES = [
    "No scheduling difficulties. The patient's preferred morning window was available.",
    "This slot came from the waitlist after a cancellation earlier the same week.",
    "The patient asked to be kept on the waitlist for any earlier opening.",
    "The visit was rescheduled once from the previous week at the patient's request.",
    "The patient prefers appointments after 2 PM because of work hours; noted for future booking.",
]

NEXT_STEPS = [
    "No follow-up required. The patient will book again as needed.",
    "A follow-up was booked before the patient left.",
    "The patient will call to book the follow-up once their schedule is confirmed.",
    "Added to the waitlist for an earlier follow-up slot if one opens.",
]

INSTRUCTIONS = {
    "New Patient Intake": (
        "Bring photo ID and insurance card, arrive fifteen minutes early to "
        "complete intake forms, and bring a list of any current prescriptions "
        "from your previous provider."
    ),
    "Annual Physical": (
        "Fast for eight hours beforehand if bloodwork is expected. Wear clothing "
        "that is easy to change out of. Bring your insurance card."
    ),
    "Post-Operative Check": (
        "Arrange transport if you were advised not to drive. Bring your discharge "
        "paperwork. Keep the dressing dry until the visit."
    ),
    "Telehealth Follow-Up": (
        "Test your camera and microphone beforehand, join from a quiet place with "
        "a stable connection, and have your pharmacy details to hand."
    ),
    "Procedure Consultation": (
        "Bring any imaging or paperwork from the referring provider, and a list of "
        "questions you would like covered."
    ),
}

CONFIRMATIONS = [
    "The patient confirmed receipt by replying to the reminder.",
    "No confirmation was received; a second reminder was sent the day before.",
    "The patient confirmed by phone when the front desk called.",
    "Delivery was logged; the patient did not need to confirm for this visit type.",
]

FOLLOWUP_STATUS = [
    "Follow-up booked and confirmed.",
    "Follow-up not yet booked. The patient is on the waitlist for the first available slot.",
    "Follow-up booked, then rescheduled once at the patient's request.",
    "Due date approaching and nothing booked yet; flagged for front-desk outreach.",
]

COORDINATION = [
    "The patient prefers the same provider for continuity where scheduling allows.",
    "Either provider is acceptable to the patient if it means an earlier slot.",
    "The patient asked for a reminder call rather than a text for the next visit.",
    "Transport is a constraint; morning slots work better than late afternoon.",
]

# Logistical, never behavioural. A missed appointment is a scheduling event with
# a cause to solve, not evidence about the person.
MISS_REASONS = [
    "Transport fell through on the day.",
    "A work conflict came up at short notice.",
    "Childcare was unavailable.",
    "The patient reported not receiving the reminder.",
    "Illness on the day of the appointment.",
]

OUTREACH = [
    "Called the same afternoon and offered three alternative slots.",
    "Sent a rebooking link and added the patient to the waitlist for earlier openings.",
    "Reached by phone; the visit was rebooked for the following week.",
    "Left a voicemail and followed up by email with available times.",
]

VISIT_TYPES = [
    ("New Patient Intake", 45, 30),
    ("Annual Physical", 30, 365),
    ("Post-Operative Check", 20, 14),
    ("Telehealth Follow-Up", 15, 90),
    ("Procedure Consultation", 30, 21),
]

PROVIDERS = ["Dr. Chen", "Dr. Alvarez", "Dr. Whitfield"]


def _date(days_ago: int) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%B %-d, %Y")


def build_documents(first: str, last: str) -> list[tuple[str, str, str]]:
    """Return (source_suffix, doc_type, raw_text_containing_the_name) tuples."""
    visit_type, duration, window = random.choice(VISIT_TYPES)
    provider = random.choice(PROVIDERS)
    days_ago = random.randint(3, 40)
    common = {
        "first": first,
        "last": last,
        "visit_type": visit_type,
        "visit_type_lower": visit_type.lower(),
        "provider": provider,
        "date": _date(days_ago),
        "duration": duration,
    }

    docs: list[tuple[str, str, str]] = [
        (
            "visit-summary",
            "visit_summary",
            VISIT_SUMMARY.format(
                **common,
                arrival=random.choice(ARRIVALS),
                scheduling_note=random.choice(SCHEDULING_NOTES),
                next_step=random.choice(NEXT_STEPS),
            ),
        ),
        (
            "prep-note",
            "prep_note",
            PREP_NOTE.format(
                **common,
                lead_time=random.choice(["three days", "two days", "one week"]),
                instructions=INSTRUCTIONS[visit_type],
                confirmation=random.choice(CONFIRMATIONS),
            ),
        ),
    ]

    if random.random() < 0.6:
        docs.append(
            (
                "followup",
                "followup_note",
                FOLLOWUP_NOTE.format(
                    **common,
                    window=window,
                    due_date=_date(days_ago - window),
                    status=random.choice(FOLLOWUP_STATUS),
                    coordination=random.choice(COORDINATION),
                ),
            )
        )

    if random.random() < 0.25:
        # A missed appointment is a DIFFERENT appointment from the one
        # summarised above. Formatting this from `common` reused the same date,
        # provider and visit type, so the patient ended up with one document
        # saying they attended and another saying they did not attend the very
        # same visit. Anything reading the whole chart -- a person or a
        # summariser -- rightly flags that as a contradiction.
        missed_type, _, _ = random.choice(VISIT_TYPES)
        docs.append(
            (
                "missed-appointment",
                "missed_appointment",
                MISSED_NOTE.format(
                    first=first,
                    last=last,
                    visit_type=missed_type,
                    visit_type_lower=missed_type.lower(),
                    provider=random.choice(PROVIDERS),
                    # Strictly earlier than the summarised visit, so the two
                    # documents describe a coherent sequence of events.
                    date=_date(days_ago + random.randint(20, 120)),
                    reason=random.choice(MISS_REASONS),
                    outreach=random.choice(OUTREACH),
                ),
            )
        )

    return docs


async def seed(limit: int | None, purge: bool, seed_value: int | None) -> int:
    if seed_value is not None:
        random.seed(seed_value)

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    total_docs = total_chunks = 0
    leaks: list[str] = []

    async with session_factory() as session:
        if purge:
            await session.execute(delete(PatientDocumentChunk))
            await session.commit()
            print("Purged existing patient document chunks.")

        # Read through the ORM: PII columns are an encrypted type decorator, so
        # raw SQL would hand back ciphertext rather than names to scrub against.
        result = await session.execute(select(PatientIdentity))
        patients = list(result.scalars().all())
        if limit:
            patients = patients[:limit]

        if not patients:
            print("No patients in identity.patient_identity. Run seed_synthetic.py first.")
            return 1

        print(f"Generating documents for {len(patients)} patients...")

        for patient in patients:
            first, last = patient.first_name, patient.last_name
            for suffix, doc_type, raw_text in build_documents(first, last):
                clean = deidentify(raw_text, patient.patient_uuid, [first, last])

                # The whole point of routing through deidentify is that this
                # check can be made. If a name survived, stop rather than write
                # PHI into the chunk table.
                for name in (first, last):
                    if len(name) > 2 and name.lower() in clean.lower():
                        leaks.append(f"{suffix} for {patient.patient_uuid}: '{name}' survived")

                chunks = await ingest_patient_document(
                    session,
                    patient_uuid=patient.patient_uuid,
                    source_doc_id=f"{patient.patient_uuid}-{suffix}",
                    doc_type=doc_type,
                    deidentified_text=clean,
                )
                total_docs += 1
                total_chunks += chunks

    await engine.dispose()

    if leaks:
        print(f"\nABORTED: {len(leaks)} de-identification failures:", file=sys.stderr)
        for leak in leaks[:10]:
            print(f"  {leak}", file=sys.stderr)
        return 1

    print(f"\nIngested {total_docs} documents -> {total_chunks} chunks")
    print("No patient name survived de-identification.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="only seed the first N patients")
    parser.add_argument("--purge", action="store_true", help="delete existing chunks first")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible output")
    args = parser.parse_args()
    return asyncio.run(seed(args.limit, args.purge, args.seed))


if __name__ == "__main__":
    raise SystemExit(main())
