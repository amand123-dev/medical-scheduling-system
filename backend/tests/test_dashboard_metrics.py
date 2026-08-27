"""Time-window behaviour of the dashboard metrics.

The deployed demo showed 0% fill rate and 0% no-show rate against a database
holding 101 appointments. The cause was the metric windowing on ``created_at``
instead of ``start_time``: the whole dataset was seeded in one batch, so every
row carried the same creation timestamp, and once that timestamp aged past the
cutoff the window was empty regardless of how much data existed.

These tests pin the window to ``start_time`` so that regression cannot return.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.scheduling import crud
from app.scheduling.models import (
    Appointment,
    AppointmentStatus,
    Provider,
    VisitType,
)


async def _fixtures(session: AsyncSession) -> tuple[Provider, VisitType]:
    from app.scheduling.schemas import ProviderCreate, VisitTypeCreate

    provider = await crud.create_provider(
        session, ProviderCreate(name="Dr. Metrics", specialty="GP")
    )
    visit_type = await crud.create_visit_type(
        session, VisitTypeCreate(name="Standard", duration_minutes=30)
    )
    return provider, visit_type


async def _add(
    session: AsyncSession,
    provider: Provider,
    visit_type: VisitType,
    *,
    days_from_now: float,
    status: AppointmentStatus,
    created_days_ago: int = 0,
) -> None:
    """Insert an appointment with independent start_time and created_at."""
    start = datetime.now(UTC) + timedelta(days=days_from_now)
    session.add(
        Appointment(
            id=uuid.uuid4(),
            provider_id=provider.id,
            patient_uuid=uuid.uuid4(),
            visit_type_id=visit_type.id,
            start_time=start,
            end_time=start + timedelta(minutes=visit_type.duration_minutes),
            status=status,
            created_at=datetime.now(UTC) - timedelta(days=created_days_ago),
        )
    )
    await session.commit()


class TestDashboardWindow:
    async def test_old_created_at_does_not_zero_out_the_metrics(self, session: AsyncSession):
        """The exact production failure: rows written long ago, happening recently.

        Every appointment here was created 200 days ago but takes place inside the
        last week. Windowing on created_at reports 0.0/0.0; windowing on
        start_time reports the real numbers.
        """
        provider, visit_type = await _fixtures(session)
        for _ in range(7):
            await _add(
                session,
                provider,
                visit_type,
                days_from_now=-3,
                status=AppointmentStatus.completed,
                created_days_ago=200,
            )
        for _ in range(3):
            await _add(
                session,
                provider,
                visit_type,
                days_from_now=-2,
                status=AppointmentStatus.no_show,
                created_days_ago=200,
            )

        metrics = await crud.get_dashboard_metrics(session, days=30)

        assert metrics["fill_rate"] == 1.0  # 7 completed / 7 (completed + scheduled)
        assert metrics["no_show_rate"] == 0.3  # 3 no-shows / 10 resolved
        assert metrics["fill_rate"] != 0.0
        assert metrics["no_show_rate"] != 0.0

    async def test_appointments_outside_the_window_are_excluded(self, session: AsyncSession):
        """Recently written rows that happened long ago must not count."""
        provider, visit_type = await _fixtures(session)
        await _add(
            session,
            provider,
            visit_type,
            days_from_now=-120,
            status=AppointmentStatus.completed,
            created_days_ago=0,
        )
        await _add(
            session,
            provider,
            visit_type,
            days_from_now=-120,
            status=AppointmentStatus.no_show,
            created_days_ago=0,
        )

        metrics = await crud.get_dashboard_metrics(session, days=30)

        assert metrics["fill_rate"] == 0.0
        assert metrics["no_show_rate"] == 0.0

    async def test_upcoming_appointments_sit_in_the_fill_rate_denominator(
        self, session: AsyncSession
    ):
        """Fill rate is completed / (scheduled + completed), per the dashboard card."""
        provider, visit_type = await _fixtures(session)
        for _ in range(3):
            await _add(
                session, provider, visit_type, days_from_now=-1, status=AppointmentStatus.completed
            )
        await _add(
            session, provider, visit_type, days_from_now=5, status=AppointmentStatus.scheduled
        )

        metrics = await crud.get_dashboard_metrics(session, days=30)

        assert metrics["fill_rate"] == 0.75  # 3 completed / 4 (3 completed + 1 upcoming)

    async def test_upcoming_appointments_are_not_counted_as_no_shows(self, session: AsyncSession):
        """An appointment that has not happened yet cannot have been missed."""
        provider, visit_type = await _fixtures(session)
        await _add(
            session, provider, visit_type, days_from_now=-1, status=AppointmentStatus.completed
        )
        for _ in range(9):
            await _add(
                session, provider, visit_type, days_from_now=4, status=AppointmentStatus.scheduled
            )

        metrics = await crud.get_dashboard_metrics(session, days=30)

        assert metrics["no_show_rate"] == 0.0

    async def test_narrower_window_excludes_older_appointments(self, session: AsyncSession):
        """days= is honoured against start_time."""
        provider, visit_type = await _fixtures(session)
        await _add(
            session, provider, visit_type, days_from_now=-20, status=AppointmentStatus.completed
        )
        await _add(
            session, provider, visit_type, days_from_now=-2, status=AppointmentStatus.completed
        )

        wide = await crud.get_dashboard_metrics(session, days=30)
        narrow = await crud.get_dashboard_metrics(session, days=7)

        assert wide["fill_rate"] == 1.0
        assert narrow["fill_rate"] == 1.0
        # The narrow window saw strictly fewer appointments, which the rate alone
        # cannot show -- assert on the underlying counts via no-show denominators.
        await _add(
            session, provider, visit_type, days_from_now=-20, status=AppointmentStatus.no_show
        )
        wide = await crud.get_dashboard_metrics(session, days=30)
        narrow = await crud.get_dashboard_metrics(session, days=7)
        assert wide["no_show_rate"] > 0.0
        assert narrow["no_show_rate"] == 0.0

    async def test_empty_database_reports_zero_not_an_error(self, session: AsyncSession):
        metrics = await crud.get_dashboard_metrics(session, days=30)
        assert metrics == {
            "fill_rate": 0.0,
            "no_show_rate": 0.0,
            "slots_recovered": 0,
            "days": 30,
        }
