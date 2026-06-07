import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.scheduling.models import Appointment, AppointmentStatus


async def compute_no_show_risk(session: AsyncSession, patient_uuid: uuid.UUID) -> float | None:
    """Return no-show ratio for a patient, or None if fewer than 3 qualifying appointments."""
    result = await session.execute(
        select(func.count()).where(
            and_(
                Appointment.patient_uuid == patient_uuid,
                Appointment.status.in_([AppointmentStatus.completed, AppointmentStatus.no_show]),
            )
        )
    )
    total = result.scalar_one()
    if total < 3:
        return None
    result2 = await session.execute(
        select(func.count()).where(
            and_(
                Appointment.patient_uuid == patient_uuid,
                Appointment.status == AppointmentStatus.no_show,
            )
        )
    )
    no_shows = result2.scalar_one()
    return no_shows / total
