import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import IdentityAccessLog, PatientIdentity
from app.identity.schemas import PatientCreate
from app.scheduling.models import StaffUser


async def create_patient(session: AsyncSession, data: PatientCreate) -> PatientIdentity:
    patient = PatientIdentity(
        patient_uuid=uuid.uuid4(),
        first_name=data.first_name,
        last_name=data.last_name,
        dob=data.dob,
        phone=data.phone,
        email=data.email,
    )
    session.add(patient)
    await session.commit()
    await session.refresh(patient)
    return patient


async def get_patient(
    session: AsyncSession,
    patient_uuid: uuid.UUID,
    accessed_by: uuid.UUID,
    action: str = "lookup",
) -> PatientIdentity | None:
    result = await session.execute(
        select(PatientIdentity).where(PatientIdentity.patient_uuid == patient_uuid)
    )
    patient = result.scalar_one_or_none()
    if patient is not None:
        log = IdentityAccessLog(
            patient_uuid=patient_uuid,
            accessed_by=accessed_by,
            action=action,
        )
        session.add(log)
        await session.commit()
    return patient


async def list_audit_log(session: AsyncSession, limit: int = 100, offset: int = 0) -> list[dict]:
    q = (
        select(
            IdentityAccessLog.id,
            IdentityAccessLog.patient_uuid,
            IdentityAccessLog.accessed_by,
            IdentityAccessLog.action,
            IdentityAccessLog.at,
            StaffUser.username.label("accessed_by_username"),
        )
        .outerjoin(StaffUser, StaffUser.id == IdentityAccessLog.accessed_by)
        .order_by(IdentityAccessLog.at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(q)).mappings().all()
    return [dict(r) for r in rows]
