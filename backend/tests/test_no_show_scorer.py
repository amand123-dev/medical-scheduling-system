"""
Phase 3: no-show ratio scorer and reminder escalation tests.

Covers:
- compute_no_show_risk: insufficient data, correct ratio, bucket boundaries
- _log_reminders: standard always, followup at medium, call_requested at high
- GET /scorer/risk/{patient_uuid} API endpoint
- GET /appointments/{appt_id}/reminders API endpoint
"""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from pytest import approx as pytest_approx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.scheduling import crud
from app.scheduling.models import (
    Appointment,
    AppointmentStatus,
    Provider,
    ReminderLog,
    ReminderType,
    VisitType,
)
from app.scheduling.schemas import AppointmentCreate, ProviderCreate, VisitTypeCreate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _provider(session: AsyncSession) -> Provider:
    return await crud.create_provider(session, ProviderCreate(name="Dr. Score", specialty="GP"))


async def _visit_type(session: AsyncSession) -> VisitType:
    return await crud.create_visit_type(
        session, VisitTypeCreate(name="Standard", duration_minutes=30)
    )


def _future(hours: int = 1) -> datetime:
    base = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    return base + timedelta(hours=hours)


async def _book(
    session: AsyncSession,
    provider: Provider,
    vt: VisitType,
    patient_uuid: uuid.UUID,
    hours_offset: int,
    status: AppointmentStatus = AppointmentStatus.scheduled,
) -> Appointment:
    """Book and immediately set status so we control the history."""
    appt, _ = await crud.create_appointment(
        session,
        AppointmentCreate(
            provider_id=provider.id,
            patient_uuid=patient_uuid,
            visit_type_id=vt.id,
            start_time=_future(hours=hours_offset),
        ),
    )
    if status != AppointmentStatus.scheduled:
        appt = await crud.update_appointment_status(session, appt.id, status)
    return appt


async def _seed_history(
    session: AsyncSession,
    provider: Provider,
    vt: VisitType,
    patient_uuid: uuid.UUID,
    no_shows: int,
    completions: int,
) -> None:
    """Seed completed and no-show appointments for a patient."""
    offset = 100
    for _ in range(no_shows):
        await _book(session, provider, vt, patient_uuid, offset, AppointmentStatus.no_show)
        offset += 1
    for _ in range(completions):
        await _book(session, provider, vt, patient_uuid, offset, AppointmentStatus.completed)
        offset += 1


# ---------------------------------------------------------------------------
# Ratio scorer unit tests
# ---------------------------------------------------------------------------


class TestRatioScorer:
    async def test_insufficient_data_below_three(self, session: AsyncSession):
        provider = await _provider(session)
        vt = await _visit_type(session)
        patient = uuid.uuid4()

        # 2 completed — below the 3-appointment minimum
        await _seed_history(session, provider, vt, patient, no_shows=0, completions=2)

        risk = await crud.compute_no_show_risk(session, patient)
        assert risk is None

    async def test_zero_no_shows_returns_zero(self, session: AsyncSession):
        provider = await _provider(session)
        vt = await _visit_type(session)
        patient = uuid.uuid4()

        await _seed_history(session, provider, vt, patient, no_shows=0, completions=5)

        risk = await crud.compute_no_show_risk(session, patient)
        assert risk == 0.0

    async def test_ratio_calculation(self, session: AsyncSession):
        """2 no-shows out of 5 total → 0.4."""
        provider = await _provider(session)
        vt = await _visit_type(session)
        patient = uuid.uuid4()

        await _seed_history(session, provider, vt, patient, no_shows=2, completions=3)

        risk = await crud.compute_no_show_risk(session, patient)
        assert risk == pytest_approx(0.4)

    async def test_all_no_shows_returns_one(self, session: AsyncSession):
        provider = await _provider(session)
        vt = await _visit_type(session)
        patient = uuid.uuid4()

        await _seed_history(session, provider, vt, patient, no_shows=4, completions=0)

        risk = await crud.compute_no_show_risk(session, patient)
        assert risk == 1.0

    async def test_cancelled_appointments_ignored(self, session: AsyncSession):
        """Cancelled appointments must not count toward the risk total."""
        provider = await _provider(session)
        vt = await _visit_type(session)
        patient = uuid.uuid4()

        await _seed_history(session, provider, vt, patient, no_shows=0, completions=2)
        # A cancellation — should NOT count toward the total
        await _book(session, provider, vt, patient, 200, AppointmentStatus.cancelled)

        risk = await crud.compute_no_show_risk(session, patient)
        # Still only 2 qualifying appointments, so insufficient_data
        assert risk is None


# ---------------------------------------------------------------------------
# Reminder escalation tests
# ---------------------------------------------------------------------------


class TestReminderEscalation:
    async def test_standard_reminder_always_logged(self, session: AsyncSession):
        provider = await _provider(session)
        vt = await _visit_type(session)
        patient = uuid.uuid4()

        appt, err = await crud.create_appointment(
            session,
            AppointmentCreate(
                provider_id=provider.id,
                patient_uuid=patient,
                visit_type_id=vt.id,
                start_time=_future(),
            ),
        )
        assert err == "ok"

        rows = (
            (
                await session.execute(
                    select(ReminderLog).where(ReminderLog.appointment_id == appt.id)
                )
            )
            .scalars()
            .all()
        )

        assert any(r.message_type == ReminderType.standard for r in rows)

    async def test_followup_logged_at_medium_risk(self, session: AsyncSession):
        """A patient at 0.4 risk (medium) gets a standard + followup reminder."""
        provider = await _provider(session)
        vt = await _visit_type(session)
        patient = uuid.uuid4()

        # 2 no-shows, 3 completions → risk = 0.4 → medium (>= 0.2 low threshold)
        await _seed_history(session, provider, vt, patient, no_shows=2, completions=3)

        appt, err = await crud.create_appointment(
            session,
            AppointmentCreate(
                provider_id=provider.id,
                patient_uuid=patient,
                visit_type_id=vt.id,
                start_time=_future(hours=200),
            ),
        )
        assert err == "ok"

        rows = (
            (
                await session.execute(
                    select(ReminderLog).where(ReminderLog.appointment_id == appt.id)
                )
            )
            .scalars()
            .all()
        )

        types = {r.message_type for r in rows}
        assert ReminderType.standard in types
        assert ReminderType.followup in types
        assert ReminderType.call_requested not in types

    async def test_call_requested_logged_at_high_risk(self, session: AsyncSession):
        """A patient at 0.6 risk (high) gets all three reminder types."""
        provider = await _provider(session)
        vt = await _visit_type(session)
        patient = uuid.uuid4()

        # 3 no-shows, 2 completions → risk = 0.6 → high (>= 0.5 high threshold)
        await _seed_history(session, provider, vt, patient, no_shows=3, completions=2)

        appt, err = await crud.create_appointment(
            session,
            AppointmentCreate(
                provider_id=provider.id,
                patient_uuid=patient,
                visit_type_id=vt.id,
                start_time=_future(hours=200),
            ),
        )
        assert err == "ok"

        rows = (
            (
                await session.execute(
                    select(ReminderLog).where(ReminderLog.appointment_id == appt.id)
                )
            )
            .scalars()
            .all()
        )

        types = {r.message_type for r in rows}
        assert ReminderType.standard in types
        assert ReminderType.followup in types
        assert ReminderType.call_requested in types

    async def test_no_extra_reminders_at_low_risk(self, session: AsyncSession):
        """A patient at zero risk gets only the standard reminder."""
        provider = await _provider(session)
        vt = await _visit_type(session)
        patient = uuid.uuid4()

        await _seed_history(session, provider, vt, patient, no_shows=0, completions=5)

        appt, err = await crud.create_appointment(
            session,
            AppointmentCreate(
                provider_id=provider.id,
                patient_uuid=patient,
                visit_type_id=vt.id,
                start_time=_future(hours=200),
            ),
        )
        assert err == "ok"

        rows = (
            (
                await session.execute(
                    select(ReminderLog).where(ReminderLog.appointment_id == appt.id)
                )
            )
            .scalars()
            .all()
        )

        types = {r.message_type for r in rows}
        assert types == {ReminderType.standard}


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestScorerAPI:
    async def test_risk_insufficient_data(self, client: AsyncClient, auth_headers: dict):
        patient = uuid.uuid4()
        resp = await client.get(f"/scorer/risk/{patient}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["bucket"] == "insufficient_data"
        assert data["score"] is None
        assert data["based_on"] == 0

    async def test_risk_low_bucket(
        self, client: AsyncClient, auth_headers: dict, session: AsyncSession
    ):
        provider = await _provider(session)
        vt = await _visit_type(session)
        patient = uuid.uuid4()

        await _seed_history(session, provider, vt, patient, no_shows=0, completions=5)

        resp = await client.get(f"/scorer/risk/{patient}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["bucket"] == "low"
        assert data["score"] == 0.0
        assert data["based_on"] == 5

    async def test_risk_high_bucket(
        self, client: AsyncClient, auth_headers: dict, session: AsyncSession
    ):
        provider = await _provider(session)
        vt = await _visit_type(session)
        patient = uuid.uuid4()

        # 3 no-shows out of 4 → 0.75 → high
        await _seed_history(session, provider, vt, patient, no_shows=3, completions=1)

        resp = await client.get(f"/scorer/risk/{patient}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["bucket"] == "high"
        assert data["based_on"] == 4

    async def test_reminders_endpoint(
        self, client: AsyncClient, auth_headers: dict, session: AsyncSession
    ):
        provider = await _provider(session)
        vt = await _visit_type(session)
        patient = uuid.uuid4()

        # High-risk patient so we get all three reminder types
        await _seed_history(session, provider, vt, patient, no_shows=3, completions=2)
        appt, _ = await crud.create_appointment(
            session,
            AppointmentCreate(
                provider_id=provider.id,
                patient_uuid=patient,
                visit_type_id=vt.id,
                start_time=_future(hours=200),
            ),
        )

        resp = await client.get(f"/appointments/{appt.id}/reminders", headers=auth_headers)
        assert resp.status_code == 200
        reminders = resp.json()
        types = {r["message_type"] for r in reminders}
        assert "standard" in types
        assert "followup" in types
        assert "call_requested" in types

    async def test_no_pii_in_risk_response(self, client: AsyncClient, auth_headers: dict):
        """Risk response must never contain name fields — only UUID and score."""
        patient = uuid.uuid4()
        resp = await client.get(f"/scorer/risk/{patient}", headers=auth_headers)
        data = resp.json()
        assert "first_name" not in data
        assert "last_name" not in data
        assert "email" not in data
