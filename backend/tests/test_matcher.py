import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.matcher.engine import backfill, decline_offer
from app.scheduling import crud
from app.scheduling.models import (
    Appointment,
    AppointmentStatus,
    PracticeSettings,
    Provider,
    VisitType,
    WaitlistEntry,
    WaitlistStatus,
)
from app.scheduling.schemas import (
    AppointmentCreate,
    ProviderCreate,
    VisitTypeCreate,
    WaitlistEntryCreate,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _provider(session: AsyncSession) -> Provider:
    return await crud.create_provider(session, ProviderCreate(name="Dr. Match", specialty="GP"))


async def _visit_type(session: AsyncSession, minutes: int = 30) -> VisitType:
    return await crud.create_visit_type(
        session, VisitTypeCreate(name="Follow-up", duration_minutes=minutes)
    )


def _future(hours: int = 1) -> datetime:
    return datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=hours)


async def _book(
    session: AsyncSession, provider: Provider, vt: VisitType, start: datetime
) -> Appointment:
    appt, _ = await crud.create_appointment(
        session,
        AppointmentCreate(
            provider_id=provider.id,
            patient_uuid=uuid.uuid4(),
            visit_type_id=vt.id,
            start_time=start,
        ),
    )
    return appt


async def _waitlist(
    session: AsyncSession,
    provider: Provider,
    vt: VisitType,
    priority: int = 0,
    decline_count: int = 0,
) -> WaitlistEntry:
    entry = await crud.create_waitlist_entry(
        session,
        WaitlistEntryCreate(
            patient_uuid=uuid.uuid4(),
            provider_id=provider.id,
            visit_type_id=vt.id,
            priority=priority,
        ),
    )
    if decline_count:
        entry.decline_count = decline_count
        await session.commit()
        await session.refresh(entry)
    return entry


async def _default_settings(session: AsyncSession) -> PracticeSettings:
    return await crud.get_or_create_settings(session)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBackfill:
    async def test_cancel_triggers_offer_to_waiting_entry(self, session: AsyncSession):
        provider = await _provider(session)
        vt = await _visit_type(session)
        start = _future()

        appt = await _book(session, provider, vt, start)
        entry = await _waitlist(session, provider, vt)

        # Cancel should trigger backfill
        cancelled = await crud.update_appointment_status(
            session, appt.id, AppointmentStatus.cancelled
        )
        offered = await backfill(session, cancelled)

        assert offered is not None
        assert offered.id == entry.id
        await session.refresh(entry)
        assert entry.status == WaitlistStatus.offered
        assert entry.offered_slot_start is not None

    async def test_backfill_returns_none_when_no_candidates(self, session: AsyncSession):
        provider = await _provider(session)
        vt = await _visit_type(session)
        start = _future()
        appt = await _book(session, provider, vt, start)
        cancelled = await crud.update_appointment_status(
            session, appt.id, AppointmentStatus.cancelled
        )

        result = await backfill(session, cancelled)
        assert result is None

    async def test_higher_priority_wins(self, session: AsyncSession):
        provider = await _provider(session)
        vt = await _visit_type(session)
        start = _future()
        appt = await _book(session, provider, vt, start)
        cancelled = await crud.update_appointment_status(
            session, appt.id, AppointmentStatus.cancelled
        )

        _ = await _waitlist(session, provider, vt, priority=0)
        high = await _waitlist(session, provider, vt, priority=5)

        offered = await backfill(session, cancelled)
        assert offered is not None
        assert offered.id == high.id

    async def test_decline_count_penalises_score(self, session: AsyncSession):
        """A patient with many declines should lose to one with zero, even at equal priority."""
        provider = await _provider(session)
        vt = await _visit_type(session)
        start = _future()
        appt = await _book(session, provider, vt, start)
        cancelled = await crud.update_appointment_status(
            session, appt.id, AppointmentStatus.cancelled
        )

        # Both priority=0; one has 3 prior declines
        clean = await _waitlist(session, provider, vt, priority=0, decline_count=0)
        _ = await _waitlist(session, provider, vt, priority=0, decline_count=3)

        offered = await backfill(session, cancelled)
        assert offered is not None
        assert offered.id == clean.id

    async def test_visit_type_too_long_excluded(self, session: AsyncSession):
        """If the freed slot is 15 min but waitlist entry needs 30 min, skip it."""
        provider = await _provider(session)
        short_vt = await _visit_type(session, minutes=15)
        long_vt = await _visit_type(session, minutes=30)
        start = _future()

        # Book a 15-min slot
        short_appt = await _book(session, provider, short_vt, start)
        cancelled = await crud.update_appointment_status(
            session, short_appt.id, AppointmentStatus.cancelled
        )

        # Waitlist entry needs 30 min — should not be offered the 15-min slot
        await _waitlist(session, provider, long_vt)
        offered = await backfill(session, cancelled)
        assert offered is None

    async def test_configurable_weights_change_ranking(self, session: AsyncSession):
        """Changing w1 (priority weight) to 0 and w2 (wait weight) high
        should flip the ranking when one entry waited much longer."""
        provider = await _provider(session)
        vt = await _visit_type(session)

        # Entry A: high priority (5), waited 0 seconds (just added)
        # Entry B: low priority (0), but will be given a simulated long wait
        entry_a = await _waitlist(session, provider, vt, priority=5)
        entry_b = await _waitlist(session, provider, vt, priority=0)

        # Simulate B waiting 8 days by backdating requested_at
        entry_b.requested_at = datetime.now(UTC) - timedelta(days=8)
        await session.commit()

        # Default weights (w1=1.0, w2=0.5, w3=0.3): A wins on priority
        settings = await _default_settings(session)
        settings.matcher_w1 = 1.0
        settings.matcher_w2 = 0.5
        await session.commit()

        start = _future()
        appt1 = await _book(session, provider, vt, start)
        c1 = await crud.update_appointment_status(session, appt1.id, AppointmentStatus.cancelled)
        from app.matcher.engine import _backfill_slot  # access internals for test

        offered1 = await _backfill_slot(session, provider.id, c1.start_time, c1.end_time, settings)
        assert offered1 is not None
        assert offered1.id == entry_a.id

        # Reset entry A's status back to waiting for the second pass
        entry_a.status = WaitlistStatus.waiting
        entry_a.offered_at = None
        entry_a.offered_slot_start = None
        entry_a.offered_slot_end = None
        await session.commit()

        # Now flip weights: w1=0 (priority doesn't matter), w2=2.0 (wait dominates)
        settings.matcher_w1 = 0.0
        settings.matcher_w2 = 2.0
        await session.commit()

        start2 = _future(hours=2)
        appt2 = await _book(session, provider, vt, start2)
        c2 = await crud.update_appointment_status(session, appt2.id, AppointmentStatus.cancelled)
        offered2 = await _backfill_slot(session, provider.id, c2.start_time, c2.end_time, settings)
        assert offered2 is not None
        assert offered2.id == entry_b.id  # B wins when wait time dominates


class TestAcceptDecline:
    async def test_decline_cascades_to_next_candidate(self, session: AsyncSession):
        provider = await _provider(session)
        vt = await _visit_type(session)
        start = _future()
        appt = await _book(session, provider, vt, start)
        cancelled = await crud.update_appointment_status(
            session, appt.id, AppointmentStatus.cancelled
        )

        first = await _waitlist(session, provider, vt, priority=5)
        second = await _waitlist(session, provider, vt, priority=1)

        offered = await backfill(session, cancelled)
        assert offered.id == first.id

        # First declines → should cascade to second
        await decline_offer(session, first.id)

        await session.refresh(first)
        await session.refresh(second)
        assert first.status == WaitlistStatus.declined
        assert first.decline_count == 1
        assert second.status == WaitlistStatus.offered

    async def test_accept_creates_appointment(self, session: AsyncSession):
        from app.matcher.engine import accept_offer

        provider = await _provider(session)
        vt = await _visit_type(session)
        start = _future()
        appt = await _book(session, provider, vt, start)
        cancelled = await crud.update_appointment_status(
            session, appt.id, AppointmentStatus.cancelled
        )

        entry = await _waitlist(session, provider, vt)
        await backfill(session, cancelled)

        new_appt = await accept_offer(session, entry.id, accepted_by_uuid=uuid.uuid4())
        assert new_appt is not None
        assert new_appt.status == AppointmentStatus.scheduled

        await session.refresh(entry)
        assert entry.status == WaitlistStatus.booked
