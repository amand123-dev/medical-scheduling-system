"""
Waitlist backfill engine.

When an appointment is cancelled, call backfill(session, cancelled_appointment).
The engine:
  1. Expires any stale offers (hold window exceeded).
  2. Finds all waiting candidates for the freed slot.
  3. Scores them: score = w1*priority + w2*normalized_wait - w3*decline_risk
  4. Offers the slot to the top scorer.
  5. On accept: books the appointment, marks entry 'booked'.
  6. On decline / expiry: cascades to the next candidate.

Weights and hold window are read from PracticeSettings (DB-stored, admin-editable).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.scheduling.crud import create_appointment, get_or_create_settings
from app.scheduling.models import (
    Appointment,
    PracticeSettings,
    VisitType,
    WaitlistEntry,
    WaitlistStatus,
)
from app.scheduling.schemas import AppointmentCreate

# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


async def backfill(session: AsyncSession, cancelled: Appointment) -> WaitlistEntry | None:
    """Triggered on appointment cancellation. Returns the entry that received an offer, or None."""
    settings = await get_or_create_settings(session)
    await _expire_stale_offers(session, settings)
    return await _backfill_slot(
        session, cancelled.provider_id, cancelled.start_time, cancelled.end_time, settings
    )


async def accept_offer(
    session: AsyncSession,
    entry_id: uuid.UUID,
    accepted_by_uuid: uuid.UUID,  # noqa: ARG001
) -> Appointment | None:
    """Accept a waitlist offer. Books the appointment; returns it or None on error."""
    result = await session.execute(select(WaitlistEntry).where(WaitlistEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if entry is None or entry.status != WaitlistStatus.offered:
        return None

    settings = await get_or_create_settings(session)

    # Check hold window hasn't expired
    if entry.offered_at and _is_expired(entry.offered_at, settings.hold_window_minutes):
        await _expire_entry(session, entry)
        await _backfill_slot(
            session, entry.provider_id, entry.offered_slot_start, entry.offered_slot_end, settings
        )
        return None

    # Book the appointment
    appt, err = await create_appointment(
        session,
        AppointmentCreate(
            provider_id=entry.provider_id,
            patient_uuid=entry.patient_uuid,
            visit_type_id=entry.visit_type_id,
            start_time=entry.offered_slot_start,
        ),
    )
    if err != "ok":
        return None

    entry.status = WaitlistStatus.booked
    await session.commit()
    return appt


async def decline_offer(session: AsyncSession, entry_id: uuid.UUID) -> None:
    """Decline a waitlist offer. Increments decline count, cascades to next candidate."""
    result = await session.execute(select(WaitlistEntry).where(WaitlistEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if entry is None or entry.status != WaitlistStatus.offered:
        return

    slot_start = entry.offered_slot_start
    slot_end = entry.offered_slot_end
    provider_id = entry.provider_id

    entry.status = WaitlistStatus.declined
    entry.decline_count += 1
    await session.commit()

    settings = await get_or_create_settings(session)
    await _backfill_slot(session, provider_id, slot_start, slot_end, settings)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _as_utc(dt: datetime) -> datetime:
    """Ensure dt is UTC-aware; SQLite returns naive datetimes in tests."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _is_expired(offered_at: datetime, hold_minutes: int) -> bool:
    return datetime.now(UTC) > _as_utc(offered_at) + timedelta(minutes=hold_minutes)


async def _expire_stale_offers(session: AsyncSession, settings: PracticeSettings) -> None:
    result = await session.execute(
        select(WaitlistEntry).where(WaitlistEntry.status == WaitlistStatus.offered)
    )
    offered = result.scalars().all()
    for entry in offered:
        if entry.offered_at and _is_expired(entry.offered_at, settings.hold_window_minutes):
            slot_start = entry.offered_slot_start
            slot_end = entry.offered_slot_end
            provider_id = entry.provider_id
            await _expire_entry(session, entry)
            # Cascade to next candidate for this slot
            await _backfill_slot(session, provider_id, slot_start, slot_end, settings)


async def _expire_entry(session: AsyncSession, entry: WaitlistEntry) -> None:
    entry.status = WaitlistStatus.expired
    await session.commit()


async def _backfill_slot(
    session: AsyncSession,
    provider_id: uuid.UUID,
    slot_start: datetime | None,
    slot_end: datetime | None,
    settings: PracticeSettings,
) -> WaitlistEntry | None:
    if slot_start is None or slot_end is None:
        return None

    slot_duration = int((slot_end - slot_start).total_seconds() / 60)

    # Fetch all waiting entries for this provider with compatible visit type
    result = await session.execute(
        select(WaitlistEntry, VisitType)
        .join(VisitType, WaitlistEntry.visit_type_id == VisitType.id)
        .where(
            and_(
                WaitlistEntry.provider_id == provider_id,
                WaitlistEntry.status == WaitlistStatus.waiting,
                VisitType.duration_minutes <= slot_duration,
            )
        )
    )
    rows = result.all()

    if not rows:
        return None

    now = datetime.now(UTC)
    candidates: list[tuple[float, WaitlistEntry]] = []

    for entry, _ in rows:
        # Skip if slot falls outside patient's preferred window
        if entry.earliest_window or entry.latest_window:
            slot_time = slot_start.time()
            if entry.earliest_window and slot_time < entry.earliest_window:
                continue
            if entry.latest_window and slot_time > entry.latest_window:
                continue

        score = _score(entry, settings, now)
        candidates.append((score, entry))

    if not candidates:
        return None

    # Highest score wins
    candidates.sort(key=lambda t: t[0], reverse=True)
    best_entry = candidates[0][1]

    # Make the offer
    best_entry.status = WaitlistStatus.offered
    best_entry.offered_at = now
    best_entry.offered_slot_start = slot_start
    best_entry.offered_slot_end = slot_end
    await session.commit()
    await session.refresh(best_entry)
    return best_entry


def _score(entry: WaitlistEntry, settings: PracticeSettings, now: datetime) -> float:
    # Normalize wait time to a 0–1 scale (7 days = max)
    wait_seconds = max(0.0, (now - _as_utc(entry.requested_at)).total_seconds())
    normalized_wait = min(wait_seconds / (7 * 24 * 3600), 1.0)

    # Decline risk: 0 at 0 declines, approaches 1 as declines accumulate
    decline_risk = min(entry.decline_count / 3.0, 1.0)

    return (
        settings.matcher_w1 * entry.priority
        + settings.matcher_w2 * normalized_wait
        - settings.matcher_w3 * decline_risk
    )
