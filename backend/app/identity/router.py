import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_session
from app.identity import crud
from app.identity.schemas import (
    AccessLogEntry,
    PatientCreate,
    PatientIdentityResponse,
    PatientUUIDResponse,
)
from app.scheduling.models import StaffRole, StaffUser

router = APIRouter(prefix="/identity", tags=["identity"])


@router.post("/patients", response_model=PatientUUIDResponse, status_code=201)
async def create_patient(
    body: PatientCreate,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(require_role(StaffRole.admin, StaffRole.front_desk)),
):
    patient = await crud.create_patient(session, body)
    return PatientUUIDResponse(patient_uuid=patient.patient_uuid)


@router.get(
    "/patients/{patient_uuid}",
    response_model=PatientIdentityResponse,
    dependencies=[Depends(require_role(StaffRole.admin, StaffRole.provider))],
)
async def get_patient(
    patient_uuid: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: StaffUser = Depends(get_current_user),
):
    patient = await crud.get_patient(session, patient_uuid, accessed_by=user.id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return patient


@router.get(
    "/audit-log",
    response_model=list[AccessLogEntry],
    dependencies=[Depends(require_role(StaffRole.admin))],
)
async def get_audit_log(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    return await crud.list_audit_log(session, limit=limit, offset=offset)
