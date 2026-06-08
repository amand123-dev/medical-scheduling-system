import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_patient
from app.database import get_session
from app.matcher.engine import accept_offer, decline_offer
from app.scheduling import crud
from app.scheduling.models import (
    Appointment,
    AppointmentStatus,
    PatientAccount,
    WaitlistEntry,
    WaitlistStatus,
)
from app.scheduling.schemas import (
    AppointmentCreate,
    AppointmentResponse,
    WaitlistEntryCreate,
    WaitlistEntryResponse,
)

router = APIRouter(prefix="/patient", tags=["patient"])

# Public router for token-based confirmation (no auth required)
public_router = APIRouter(prefix="/waitlist-confirm", tags=["patient-confirm"])


# ── Identity ──────────────────────────────────────────────────────────────────


@router.get("/me")
async def get_my_identity(
    current: PatientAccount = Depends(get_current_patient),
    session: AsyncSession = Depends(get_session),
):
    row = await session.execute(
        text(
            "SELECT first_name, last_name, dob, phone, email FROM identity.patient_identity "
            "WHERE patient_uuid = :uuid"
        ),
        {"uuid": str(current.patient_uuid)},
    )
    identity = row.mappings().one_or_none()
    if identity is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    return {
        "patient_uuid": str(current.patient_uuid),
        "email": current.email,
        **dict(identity),
    }


# ── Appointments ──────────────────────────────────────────────────────────────


@router.get("/appointments", response_model=list[AppointmentResponse])
async def my_appointments(
    current: PatientAccount = Depends(get_current_patient),
    session: AsyncSession = Depends(get_session),
):
    return await crud.list_appointments(session, patient_uuid=current.patient_uuid)


@router.post("/appointments", response_model=AppointmentResponse, status_code=201)
async def book_appointment(
    body: AppointmentCreate,
    current: PatientAccount = Depends(get_current_patient),
    session: AsyncSession = Depends(get_session),
):
    # Force patient_uuid from token — ignore any value in body
    safe_body = AppointmentCreate(
        provider_id=body.provider_id,
        patient_uuid=current.patient_uuid,
        visit_type_id=body.visit_type_id,
        start_time=body.start_time,
    )
    appt, err = await crud.create_appointment(session, safe_body)
    if err == "overlap":
        raise HTTPException(status_code=409, detail="Time slot is already booked")
    if err == "blocked":
        raise HTTPException(status_code=409, detail="That date is unavailable")
    if err != "ok":
        raise HTTPException(status_code=400, detail=err)
    return appt


@router.patch("/appointments/{appt_id}/cancel", response_model=AppointmentResponse)
async def cancel_my_appointment(
    appt_id: uuid.UUID,
    current: PatientAccount = Depends(get_current_patient),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Appointment).where(Appointment.id == appt_id))
    appt = result.scalar_one_or_none()
    if appt is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.patient_uuid != current.patient_uuid:
        raise HTTPException(status_code=403, detail="Not your appointment")
    if appt.status != AppointmentStatus.scheduled:
        raise HTTPException(status_code=409, detail="Appointment cannot be cancelled")

    appt = await crud.update_appointment_status(session, appt_id, AppointmentStatus.cancelled)
    from app.matcher.engine import backfill
    await backfill(session, appt)
    return appt


# ── Waitlist ──────────────────────────────────────────────────────────────────


@router.post("/waitlist", response_model=WaitlistEntryResponse, status_code=201)
async def join_waitlist(
    body: WaitlistEntryCreate,
    current: PatientAccount = Depends(get_current_patient),
    session: AsyncSession = Depends(get_session),
):
    safe_body = WaitlistEntryCreate(
        patient_uuid=current.patient_uuid,
        provider_id=body.provider_id,
        visit_type_id=body.visit_type_id,
        earliest_window=body.earliest_window,
        latest_window=body.latest_window,
        priority=0,
    )
    return await crud.create_waitlist_entry(session, safe_body)


@router.get("/waitlist", response_model=list[WaitlistEntryResponse])
async def my_waitlist(
    current: PatientAccount = Depends(get_current_patient),
    session: AsyncSession = Depends(get_session),
):
    return await crud.list_waitlist(session, patient_uuid=current.patient_uuid)


@router.patch("/waitlist/{entry_id}/accept", response_model=AppointmentResponse)
async def accept_my_offer(
    entry_id: uuid.UUID,
    current: PatientAccount = Depends(get_current_patient),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(WaitlistEntry).where(WaitlistEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if entry is None or entry.patient_uuid != current.patient_uuid:
        raise HTTPException(status_code=404, detail="Offer not found")
    appt = await accept_offer(session, entry_id, current.patient_uuid)
    if appt is None:
        raise HTTPException(status_code=410, detail="Offer expired — a new offer may be on its way")
    return appt


@router.patch("/waitlist/{entry_id}/decline")
async def decline_my_offer(
    entry_id: uuid.UUID,
    current: PatientAccount = Depends(get_current_patient),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(WaitlistEntry).where(WaitlistEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if entry is None or entry.patient_uuid != current.patient_uuid:
        raise HTTPException(status_code=404, detail="Offer not found")
    await decline_offer(session, entry_id)
    return {"status": "declined"}


# ── Token-based confirm/decline (public, no auth) ─────────────────────────────


@public_router.get("/{token}/accept")
async def confirm_via_token(token: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(WaitlistEntry).where(WaitlistEntry.offer_token == token)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Link not found or already used")
    if entry.status != WaitlistStatus.offered:
        return {"status": entry.status, "message": "This offer has already been resolved."}
    appt = await accept_offer(session, entry.id, entry.patient_uuid)
    if appt is None:
        return {"status": "expired", "message": "Sorry, this offer expired. A new one may be sent shortly."}
    return {"status": "booked", "message": "Your appointment is confirmed!", "appointment_id": str(appt.id)}


@public_router.get("/{token}/decline")
async def decline_via_token(token: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(WaitlistEntry).where(WaitlistEntry.offer_token == token)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Link not found or already used")
    if entry.status != WaitlistStatus.offered:
        return {"status": entry.status, "message": "This offer has already been resolved."}
    await decline_offer(session, entry.id)
    return {"status": "declined", "message": "Got it — we'll offer this slot to the next person on the list."}
