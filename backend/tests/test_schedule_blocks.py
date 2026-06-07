"""Tests for schedule blocks and find_next_available."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.scheduling import crud
from app.scheduling.models import Provider, VisitType
from app.scheduling.schemas import AppointmentCreate, ScheduleBlockCreate


@pytest_asyncio.fixture
async def provider(session: AsyncSession) -> Provider:
    p = Provider(id=uuid.uuid4(), name="Dr. Block Test", specialty="General")
    session.add(p)
    await session.commit()
    return p


@pytest_asyncio.fixture
async def other_provider(session: AsyncSession) -> Provider:
    p = Provider(id=uuid.uuid4(), name="Dr. Other", specialty="General")
    session.add(p)
    await session.commit()
    return p


@pytest_asyncio.fixture
async def visit_type(session: AsyncSession) -> VisitType:
    vt = VisitType(id=uuid.uuid4(), name="Follow-up", duration_minutes=30)
    session.add(vt)
    await session.commit()
    return vt


class TestScheduleBlockCRUD:
    async def test_create_and_list(self, session: AsyncSession, provider: Provider):
        from datetime import date

        block = await crud.create_schedule_block(
            session,
            ScheduleBlockCreate(
                provider_id=provider.id,
                start_date=date(2030, 1, 1),
                end_date=date(2030, 1, 5),
                reason="Vacation",
            ),
        )
        assert block.id is not None
        assert block.reason == "Vacation"

        blocks = await crud.list_schedule_blocks(session)
        assert len(blocks) == 1

    async def test_clinic_wide_block_no_provider(self, session: AsyncSession):
        from datetime import date

        block = await crud.create_schedule_block(
            session,
            ScheduleBlockCreate(start_date=date(2030, 2, 1), end_date=date(2030, 2, 3)),
        )
        assert block.provider_id is None

    async def test_delete_block(self, session: AsyncSession, provider: Provider):
        from datetime import date

        block = await crud.create_schedule_block(
            session,
            ScheduleBlockCreate(
                provider_id=provider.id,
                start_date=date(2030, 3, 1),
                end_date=date(2030, 3, 1),
            ),
        )
        deleted = await crud.delete_schedule_block(session, block.id)
        assert deleted is True
        assert len(await crud.list_schedule_blocks(session)) == 0

    async def test_delete_nonexistent_returns_false(self, session: AsyncSession):
        assert await crud.delete_schedule_block(session, uuid.uuid4()) is False

    async def test_is_date_blocked_per_provider(
        self, session: AsyncSession, provider: Provider, other_provider: Provider
    ):
        from datetime import date

        await crud.create_schedule_block(
            session,
            ScheduleBlockCreate(
                provider_id=provider.id,
                start_date=date(2030, 4, 10),
                end_date=date(2030, 4, 12),
            ),
        )
        assert await crud.is_date_blocked(session, provider.id, date(2030, 4, 11)) is True
        # Other provider not blocked
        assert await crud.is_date_blocked(session, other_provider.id, date(2030, 4, 11)) is False

    async def test_clinic_wide_block_applies_to_all(
        self, session: AsyncSession, provider: Provider, other_provider: Provider
    ):
        from datetime import date

        await crud.create_schedule_block(
            session,
            ScheduleBlockCreate(start_date=date(2030, 5, 1), end_date=date(2030, 5, 1)),
        )
        assert await crud.is_date_blocked(session, provider.id, date(2030, 5, 1)) is True
        assert await crud.is_date_blocked(session, other_provider.id, date(2030, 5, 1)) is True

    async def test_list_blocks_filtered_by_provider(
        self, session: AsyncSession, provider: Provider, other_provider: Provider
    ):
        from datetime import date

        await crud.create_schedule_block(
            session,
            ScheduleBlockCreate(
                provider_id=provider.id, start_date=date(2030, 6, 1), end_date=date(2030, 6, 1)
            ),
        )
        await crud.create_schedule_block(
            session,
            ScheduleBlockCreate(
                provider_id=other_provider.id,
                start_date=date(2030, 6, 2),
                end_date=date(2030, 6, 2),
            ),
        )
        # Clinic-wide block
        await crud.create_schedule_block(
            session,
            ScheduleBlockCreate(start_date=date(2030, 6, 3), end_date=date(2030, 6, 3)),
        )

        # list for provider should include own + clinic-wide, not other_provider's
        blocks = await crud.list_schedule_blocks(session, provider_id=provider.id)
        block_dates = {b.start_date.isoformat() for b in blocks}
        assert "2030-06-01" in block_dates  # own block
        assert "2030-06-03" in block_dates  # clinic-wide
        assert "2030-06-02" not in block_dates  # other provider's block


class TestBookingBlocked:
    async def test_booking_on_blocked_date_rejected(
        self, session: AsyncSession, provider: Provider, visit_type: VisitType
    ):
        from datetime import date

        await crud.create_schedule_block(
            session,
            ScheduleBlockCreate(
                provider_id=provider.id,
                start_date=date(2030, 7, 15),
                end_date=date(2030, 7, 15),
            ),
        )
        appt, err = await crud.create_appointment(
            session,
            AppointmentCreate(
                provider_id=provider.id,
                patient_uuid=uuid.uuid4(),
                visit_type_id=visit_type.id,
                start_time=datetime(2030, 7, 15, 10, 0, tzinfo=UTC),
            ),
        )
        assert appt is None
        assert err == "blocked"

    async def test_booking_adjacent_to_block_succeeds(
        self, session: AsyncSession, provider: Provider, visit_type: VisitType
    ):
        from datetime import date

        await crud.create_schedule_block(
            session,
            ScheduleBlockCreate(
                provider_id=provider.id,
                start_date=date(2030, 8, 15),
                end_date=date(2030, 8, 15),
            ),
        )
        appt, err = await crud.create_appointment(
            session,
            AppointmentCreate(
                provider_id=provider.id,
                patient_uuid=uuid.uuid4(),
                visit_type_id=visit_type.id,
                start_time=datetime(2030, 8, 16, 10, 0, tzinfo=UTC),
            ),
        )
        assert err == "ok"
        assert appt is not None


class TestFindNextAvailable:
    async def test_returns_slot_in_working_hours(
        self, session: AsyncSession, provider: Provider, visit_type: VisitType
    ):
        after = datetime(2030, 9, 1, 0, 0, tzinfo=UTC)
        start = await crud.find_next_available(session, provider.id, visit_type.id, after)
        assert start is not None
        settings = await crud.get_or_create_settings(session)
        assert start.hour >= settings.work_start_hour
        assert (
            start + timedelta(minutes=visit_type.duration_minutes)
        ).hour <= settings.work_end_hour

    async def test_skips_blocked_date(
        self, session: AsyncSession, provider: Provider, visit_type: VisitType
    ):
        from datetime import date

        # Block 5 consecutive days so we can verify the result is at least a day after
        after = datetime(2030, 10, 1, 7, 0, tzinfo=UTC)
        await crud.create_schedule_block(
            session,
            ScheduleBlockCreate(
                provider_id=provider.id,
                start_date=date(2030, 10, 1),
                end_date=date(2030, 10, 5),
            ),
        )
        start = await crud.find_next_available(session, provider.id, visit_type.id, after)
        assert start is not None
        assert start.date() >= date(2030, 10, 6)

    async def test_skips_fully_booked_slot(
        self, session: AsyncSession, provider: Provider, visit_type: VisitType
    ):
        settings = await crud.get_or_create_settings(session)
        first_slot = datetime(2030, 11, 1, settings.work_start_hour, 0, tzinfo=UTC)
        # Pre-book the first slot
        await crud.create_appointment(
            session,
            AppointmentCreate(
                provider_id=provider.id,
                patient_uuid=uuid.uuid4(),
                visit_type_id=visit_type.id,
                start_time=first_slot,
            ),
        )
        after = datetime(2030, 11, 1, 0, 0, tzinfo=UTC)
        start = await crud.find_next_available(session, provider.id, visit_type.id, after)
        assert start is not None
        # Must be different from (or after) the booked slot
        assert start >= first_slot + timedelta(minutes=visit_type.duration_minutes)

    async def test_invalid_visit_type_returns_none(self, session: AsyncSession, provider: Provider):
        after = datetime(2030, 12, 1, 0, 0, tzinfo=UTC)
        result = await crud.find_next_available(session, provider.id, uuid.uuid4(), after)
        assert result is None


class TestScheduleBlocksAPI:
    async def test_list_blocks_requires_auth(self, client: AsyncClient):
        resp = await client.get("/schedule-blocks")
        assert resp.status_code in (401, 403)

    async def test_create_and_list_blocks(
        self, client: AsyncClient, auth_headers: dict, provider: Provider
    ):
        payload = {
            "provider_id": str(provider.id),
            "start_date": "2031-01-10",
            "end_date": "2031-01-12",
            "reason": "Conference",
        }
        resp = await client.post("/schedule-blocks", json=payload, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["reason"] == "Conference"

        list_resp = await client.get("/schedule-blocks", headers=auth_headers)
        assert list_resp.status_code == 200
        assert any(b["reason"] == "Conference" for b in list_resp.json())

    async def test_delete_block(self, client: AsyncClient, auth_headers: dict):
        payload = {"start_date": "2031-02-01", "end_date": "2031-02-01"}
        create_resp = await client.post("/schedule-blocks", json=payload, headers=auth_headers)
        block_id = create_resp.json()["id"]

        del_resp = await client.delete(f"/schedule-blocks/{block_id}", headers=auth_headers)
        assert del_resp.status_code == 204

    async def test_booking_on_blocked_date_returns_409(
        self, client: AsyncClient, auth_headers: dict, provider: Provider, visit_type: VisitType
    ):
        # Create a clinic-wide block
        await client.post(
            "/schedule-blocks",
            json={"start_date": "2031-03-15", "end_date": "2031-03-15"},
            headers=auth_headers,
        )
        resp = await client.post(
            "/appointments",
            json={
                "provider_id": str(provider.id),
                "patient_uuid": str(uuid.uuid4()),
                "visit_type_id": str(visit_type.id),
                "start_time": "2031-03-15T10:00:00Z",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert "blocked" in resp.json()["detail"].lower()
