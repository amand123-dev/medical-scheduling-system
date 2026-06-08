import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.config import settings as app_settings
from app.database import get_session
from app.matcher.engine import accept_offer, backfill, decline_offer
from app.scheduling import crud
from app.scheduling.models import (
    Appointment,
    AppointmentStatus,
    ReminderLog,
    StaffRole,
    StaffUser,
    WaitlistEntry,
    WaitlistStatus,
)
from app.scheduling.schemas import (
    AppointmentCreate,
    AppointmentResponse,
    DashboardMetrics,
    MLPredictRequest,
    MLPredictResponse,
    MLRiskResponse,
    NextAvailableResponse,
    OutreachEventResponse,
    PracticeSettingsResponse,
    PracticeSettingsUpdate,
    ProviderCreate,
    ProviderResponse,
    ProviderUpdate,
    ReminderLogResponse,
    RiskResponse,
    ScheduleBlockBulkCreate,
    ScheduleBlockCreate,
    ScheduleBlockResponse,
    VisitTypeCreate,
    VisitTypeResponse,
    WaitlistEntryCreate,
    WaitlistEntryResponse,
)

router = APIRouter(tags=["scheduling"])


# --- Providers ---


@router.get("/providers", response_model=list[ProviderResponse])
async def list_providers(
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(get_current_user),
):
    return await crud.list_providers(session)


@router.post("/providers", response_model=ProviderResponse, status_code=201)
async def create_provider(
    body: ProviderCreate,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(require_role(StaffRole.admin)),
):
    return await crud.create_provider(session, body)


@router.patch("/providers/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: uuid.UUID,
    body: ProviderUpdate,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(require_role(StaffRole.admin)),
):
    provider = await crud.update_provider(session, provider_id, body)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider


# --- Visit Types ---


@router.get("/visit-types", response_model=list[VisitTypeResponse])
async def list_visit_types(
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(get_current_user),
):
    return await crud.list_visit_types(session)


@router.post("/visit-types", response_model=VisitTypeResponse, status_code=201)
async def create_visit_type(
    body: VisitTypeCreate,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(require_role(StaffRole.admin)),
):
    return await crud.create_visit_type(session, body)


# --- Appointments ---


@router.get("/appointments", response_model=list[AppointmentResponse])
async def list_appointments(
    provider_id: uuid.UUID | None = Query(None),
    date: datetime | None = Query(None),
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(get_current_user),
):
    return await crud.list_appointments(session, provider_id=provider_id, date=date)


@router.post("/appointments", response_model=AppointmentResponse, status_code=201)
async def create_appointment(
    body: AppointmentCreate,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(require_role(StaffRole.admin, StaffRole.front_desk)),
):
    appt, err = await crud.create_appointment(session, body)
    if err == "visit_type_not_found":
        raise HTTPException(status_code=404, detail="Visit type not found")
    if err == "overlap":
        raise HTTPException(status_code=409, detail="Slot overlaps with an existing appointment")
    if err == "blocked":
        raise HTTPException(status_code=409, detail="That date is blocked for this provider")
    return appt


@router.patch("/appointments/{appt_id}/cancel", response_model=AppointmentResponse)
async def cancel_appointment(
    appt_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(require_role(StaffRole.admin, StaffRole.front_desk)),
):
    appt = await crud.update_appointment_status(session, appt_id, AppointmentStatus.cancelled)
    if appt is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    await backfill(session, appt)
    return appt


@router.patch("/appointments/{appt_id}/complete", response_model=AppointmentResponse)
async def complete_appointment(
    appt_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(require_role(StaffRole.admin, StaffRole.provider)),
):
    appt = await crud.update_appointment_status(session, appt_id, AppointmentStatus.completed)
    if appt is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appt


@router.patch("/appointments/{appt_id}/no-show", response_model=AppointmentResponse)
async def no_show_appointment(
    appt_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(require_role(StaffRole.admin, StaffRole.front_desk)),
):
    appt = await crud.update_appointment_status(session, appt_id, AppointmentStatus.no_show)
    if appt is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appt


# --- Waitlist ---


@router.get("/waitlist", response_model=list[WaitlistEntryResponse])
async def list_waitlist(
    provider_id: uuid.UUID | None = Query(None),
    entry_status: WaitlistStatus | None = Query(None, alias="status"),
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(get_current_user),
):
    return await crud.list_waitlist(session, provider_id=provider_id, status=entry_status)


@router.post("/waitlist", response_model=WaitlistEntryResponse, status_code=201)
async def add_to_waitlist(
    body: WaitlistEntryCreate,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(require_role(StaffRole.admin, StaffRole.front_desk)),
):
    return await crud.create_waitlist_entry(session, body)


@router.post("/waitlist/{entry_id}/offer", response_model=WaitlistEntryResponse)
async def manual_offer_slot(
    entry_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(require_role(StaffRole.admin, StaffRole.front_desk)),
):
    entry, err = await crud.manual_offer_slot(session, entry_id)
    if err == "not_found":
        raise HTTPException(status_code=404, detail="Waitlist entry not found")
    if err == "not_waiting":
        raise HTTPException(status_code=409, detail="Entry is not in waiting status")
    if err == "no_slot":
        raise HTTPException(status_code=404, detail="No available slot found in the next 60 days")
    return entry


@router.patch("/waitlist/{entry_id}/accept", response_model=AppointmentResponse)
async def accept_waitlist_offer(
    entry_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: StaffUser = Depends(get_current_user),
):
    appt = await accept_offer(session, entry_id, accepted_by_uuid=user.id)
    if appt is None:
        raise HTTPException(
            status_code=409,
            detail="Offer not available — may have expired or already been actioned.",
        )
    return appt


@router.patch("/waitlist/{entry_id}/decline", response_model=WaitlistEntryResponse)
async def decline_waitlist_offer(
    entry_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(get_current_user),
):
    await decline_offer(session, entry_id)
    result = await session.execute(select(WaitlistEntry).where(WaitlistEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")
    return entry


# --- Reminders ---


@router.get("/appointments/{appt_id}/reminders", response_model=list[ReminderLogResponse])
async def get_reminders(
    appt_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(get_current_user),
):
    result = await session.execute(select(ReminderLog).where(ReminderLog.appointment_id == appt_id))
    return list(result.scalars().all())


# --- Risk scoring ---


@router.get("/scorer/risk/{patient_uuid}", response_model=RiskResponse)
async def get_no_show_risk(
    patient_uuid: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(get_current_user),
):
    risk = await crud.compute_no_show_risk(session, patient_uuid)
    if risk is None:
        return RiskResponse(
            patient_uuid=patient_uuid, score=None, bucket="insufficient_data", based_on=0
        )

    count_q = await session.execute(
        select(func.count()).where(
            and_(
                Appointment.patient_uuid == patient_uuid,
                Appointment.status.in_([AppointmentStatus.completed, AppointmentStatus.no_show]),
            )
        )
    )
    based_on = count_q.scalar_one()

    if risk < app_settings.risk_low_threshold:
        bucket = "low"
    elif risk < app_settings.risk_high_threshold:
        bucket = "medium"
    else:
        bucket = "high"

    return RiskResponse(patient_uuid=patient_uuid, score=risk, bucket=bucket, based_on=based_on)


# --- ML risk by patient UUID (demo-only, reads sidecar JSON) ---

_PROFILES_PATH = Path(__file__).resolve().parents[2] / "data" / "demo_patient_profiles.json"


@router.get("/scorer/ml-risk/{patient_uuid}", response_model=MLRiskResponse)
async def get_ml_no_show_risk(
    patient_uuid: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(get_current_user),
):
    from app.scorer.ml import predict as ml_predict_fn

    if not _PROFILES_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="Demo profiles not found. Run scripts/seed_synthetic.py first.",
        )
    profiles = json.loads(_PROFILES_PATH.read_text())
    profile = profiles.get(str(patient_uuid))
    if profile is None:
        raise HTTPException(status_code=404, detail="No demo profile for this patient.")

    # Compute wait_days from next scheduled appointment, else most recent appointment
    result = await session.execute(
        select(Appointment)
        .where(
            and_(
                Appointment.patient_uuid == patient_uuid,
                Appointment.status == AppointmentStatus.scheduled,
            )
        )
        .order_by(Appointment.start_time.asc())
        .limit(1)
    )
    appt = result.scalar_one_or_none()
    if appt is not None:
        wait_days = max(0, (appt.start_time.date() - datetime.now(UTC).date()).days)
    else:
        result2 = await session.execute(
            select(Appointment)
            .where(Appointment.patient_uuid == patient_uuid)
            .order_by(Appointment.created_at.desc())
            .limit(1)
        )
        any_appt = result2.scalar_one_or_none()
        wait_days = (
            max(0, (any_appt.start_time.date() - any_appt.created_at.date()).days)
            if any_appt
            else 0
        )

    sms_result = await session.execute(
        select(func.count())
        .select_from(ReminderLog)
        .join(Appointment, Appointment.id == ReminderLog.appointment_id)
        .where(Appointment.patient_uuid == patient_uuid)
    )
    sms_received = 1 if sms_result.scalar_one() > 0 else 0

    features = {
        "Age": profile["age"],
        "Gender": profile["gender"],
        "Scholarship": profile["scholarship"],
        "Hipertension": profile["hipertension"],
        "Diabetes": profile["diabetes"],
        "Alcoholism": profile["alcoholism"],
        "Handcap": profile["handcap"],
        "SMS_received": sms_received,
        "wait_days": wait_days,
    }
    prob = ml_predict_fn(features)
    if prob is None:
        raise HTTPException(
            status_code=503,
            detail="ML model not available. Run scripts/train_noshow.py first.",
        )

    bucket = "low" if prob < 0.2 else ("medium" if prob < 0.5 else "high")
    return MLRiskResponse(
        patient_uuid=patient_uuid,
        probability=round(prob, 4),
        bucket=bucket,
        note="Demo model only — trained on public Kaggle dataset with synthetic features.",
        features_used={k: v for k, v in features.items() if k != "wait_days"},
        wait_days=wait_days,
    )


# --- ML predict (demo-only) ---


@router.post("/scorer/predict", response_model=MLPredictResponse)
async def ml_predict(
    body: MLPredictRequest,
    _user: StaffUser = Depends(get_current_user),
):
    from app.scorer.ml import predict as ml_predict_fn

    features = {
        "Age": body.age,
        "Gender": body.gender,
        "Scholarship": body.scholarship,
        "Hipertension": body.hipertension,
        "Diabetes": body.diabetes,
        "Alcoholism": body.alcoholism,
        "Handcap": body.handcap,
        "SMS_received": body.sms_received,
        "wait_days": body.wait_days,
    }
    prob = ml_predict_fn(features)
    if prob is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "ML model not available. Run `python scripts/train_noshow.py` "
                "with the Kaggle dataset to generate models/noshow_rf.joblib."
            ),
        )

    bucket = "low" if prob < 0.2 else ("medium" if prob < 0.5 else "high")
    return MLPredictResponse(
        probability=round(prob, 4),
        bucket=bucket,
        note=(
            "Demo endpoint only. This model was trained on the public Kaggle no-show dataset "
            "and requires demographic features not stored in operational tables "
            "(data-minimization by design). Do not use for live appointment risk scoring."
        ),
    )


# --- Dashboard ---


@router.get("/dashboard/metrics", response_model=DashboardMetrics)
async def dashboard_metrics(
    days: int = Query(30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(get_current_user),
):
    metrics = await crud.get_dashboard_metrics(session, days)
    return DashboardMetrics(**metrics)


# --- Settings ---


@router.get("/settings", response_model=PracticeSettingsResponse)
async def get_settings(
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(get_current_user),
):
    return await crud.get_or_create_settings(session)


@router.patch("/settings", response_model=PracticeSettingsResponse)
async def update_settings(
    body: PracticeSettingsUpdate,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(require_role(StaffRole.admin)),
):
    return await crud.update_settings(session, body)


# --- Schedule blocks ---


@router.get("/schedule-blocks", response_model=list[ScheduleBlockResponse])
async def list_schedule_blocks(
    provider_id: uuid.UUID | None = Query(None),
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(get_current_user),
):
    return await crud.list_schedule_blocks(session, provider_id=provider_id)


@router.post("/schedule-blocks", response_model=ScheduleBlockResponse, status_code=201)
async def create_schedule_block(
    body: ScheduleBlockCreate,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(require_role(StaffRole.admin, StaffRole.front_desk)),
):
    return await crud.create_schedule_block(session, body)


@router.post("/schedule-blocks/bulk", status_code=201)
async def create_schedule_blocks_bulk(
    body: ScheduleBlockBulkCreate,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(require_role(StaffRole.admin, StaffRole.front_desk)),
):
    return await crud.create_schedule_blocks_bulk(session, body.items)


@router.delete("/schedule-blocks/{block_id}", status_code=204)
async def delete_schedule_block(
    block_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(require_role(StaffRole.admin)),
):
    deleted = await crud.delete_schedule_block(session, block_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Block not found")


# --- Outreach log ---


@router.get("/outreach-log", response_model=list[OutreachEventResponse])
async def get_outreach_log(
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(get_current_user),
):
    return await crud.get_outreach_log(session, limit=limit)


# --- Next available slot ---


@router.get("/appointments/next-available", response_model=NextAvailableResponse)
async def next_available(
    provider_id: uuid.UUID = Query(...),
    visit_type_id: uuid.UUID = Query(...),
    after: datetime | None = Query(None),
    tz_offset: int = Query(0),  # JS getTimezoneOffset() minutes, positive = west of UTC
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(get_current_user),
):
    start = await crud.find_next_available(session, provider_id, visit_type_id, after, tz_offset)
    if start is None:
        raise HTTPException(status_code=404, detail="No available slot found in the next 60 days")
    vt = await crud.get_visit_type(session, visit_type_id)
    from datetime import timedelta

    end = start + timedelta(minutes=vt.duration_minutes)
    return NextAvailableResponse(
        provider_id=provider_id,
        visit_type_id=visit_type_id,
        start_time=start,
        end_time=end,
    )
