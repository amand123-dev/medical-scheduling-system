import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.scheduling.models import (
    Appointment,
    AppointmentStatus,
    PracticeSettings,
    Provider,
    ReminderChannel,
    ReminderLog,
    ReminderType,
    ScheduleBlock,
    VisitType,
    WaitlistEntry,
    WaitlistStatus,
)
from app.scheduling.schemas import (
    AppointmentCreate,
    PracticeSettingsUpdate,
    ProviderCreate,
    ScheduleBlockCreate,
    VisitTypeCreate,
    WaitlistEntryCreate,
)
from app.scorer.ratio import compute_no_show_risk


async def list_providers(session: AsyncSession, active_only: bool = True) -> list[Provider]:
    q = select(Provider)
    if active_only:
        q = q.where(Provider.is_active == True)  # noqa: E712
    result = await session.execute(q)
    return list(result.scalars().all())


async def create_provider(session: AsyncSession, data: ProviderCreate) -> Provider:
    provider = Provider(id=uuid.uuid4(), name=data.name, specialty=data.specialty)
    session.add(provider)
    await session.commit()
    await session.refresh(provider)
    return provider


async def list_visit_types(session: AsyncSession) -> list[VisitType]:
    result = await session.execute(select(VisitType))
    return list(result.scalars().all())


async def create_visit_type(session: AsyncSession, data: VisitTypeCreate) -> VisitType:
    vt = VisitType(
        id=uuid.uuid4(),
        name=data.name,
        duration_minutes=data.duration_minutes,
        is_new_patient=data.is_new_patient,
    )
    session.add(vt)
    await session.commit()
    await session.refresh(vt)
    return vt


async def get_visit_type(session: AsyncSession, visit_type_id: uuid.UUID) -> VisitType | None:
    result = await session.execute(select(VisitType).where(VisitType.id == visit_type_id))
    return result.scalar_one_or_none()


async def list_appointments(
    session: AsyncSession,
    provider_id: uuid.UUID | None = None,
    date: datetime | None = None,
) -> list[Appointment]:
    q = select(Appointment)
    if provider_id:
        q = q.where(Appointment.provider_id == provider_id)
    if date:
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        q = q.where(and_(Appointment.start_time >= day_start, Appointment.start_time < day_end))
    result = await session.execute(q)
    return list(result.scalars().all())


async def _has_overlap(
    session: AsyncSession,
    provider_id: uuid.UUID,
    start: datetime,
    end: datetime,
    exclude_id: uuid.UUID | None = None,
    buffer_minutes: int = 0,
) -> bool:
    # Buffer extends the exclusive zone after an existing appointment ends.
    # New slot [start, end] conflicts with existing [A_start, A_end] when:
    #   A_start < end  AND  A_end > start - buffer
    buffer = timedelta(minutes=buffer_minutes)
    q = select(Appointment).where(
        and_(
            Appointment.provider_id == provider_id,
            Appointment.status != AppointmentStatus.cancelled,
            Appointment.start_time < end,
            Appointment.end_time > start - buffer,
        )
    )
    if exclude_id:
        q = q.where(Appointment.id != exclude_id)
    result = await session.execute(q)
    return result.scalar_one_or_none() is not None


async def _log_reminders(
    session: AsyncSession,
    appointment: Appointment,
    risk: float | None,
    settings: "PracticeSettings | None" = None,
) -> None:
    from app.config import settings as app_settings

    low_thresh = settings.risk_low_threshold if settings else app_settings.risk_low_threshold
    high_thresh = settings.risk_high_threshold if settings else app_settings.risk_high_threshold

    session.add(
        ReminderLog(
            id=uuid.uuid4(),
            appointment_id=appointment.id,
            channel=ReminderChannel.sms,
            message_type=ReminderType.standard,
        )
    )
    if risk is not None and risk >= low_thresh:
        session.add(
            ReminderLog(
                id=uuid.uuid4(),
                appointment_id=appointment.id,
                channel=ReminderChannel.email,
                message_type=ReminderType.followup,
            )
        )
    if risk is not None and risk >= high_thresh:
        session.add(
            ReminderLog(
                id=uuid.uuid4(),
                appointment_id=appointment.id,
                channel=ReminderChannel.call,
                message_type=ReminderType.call_requested,
            )
        )


async def create_appointment(
    session: AsyncSession, data: AppointmentCreate
) -> tuple[Appointment, str]:
    vt = await get_visit_type(session, data.visit_type_id)
    if vt is None:
        return None, "visit_type_not_found"

    end_time = data.start_time + timedelta(minutes=vt.duration_minutes)
    db_settings = await get_or_create_settings(session)

    if await _has_overlap(
        session,
        data.provider_id,
        data.start_time,
        end_time,
        buffer_minutes=db_settings.buffer_minutes,
    ):
        return None, "overlap"

    if await is_date_blocked(session, data.provider_id, data.start_time.date()):
        return None, "blocked"

    risk = await compute_no_show_risk(session, data.patient_uuid)

    appt = Appointment(
        id=uuid.uuid4(),
        provider_id=data.provider_id,
        patient_uuid=data.patient_uuid,
        visit_type_id=data.visit_type_id,
        start_time=data.start_time,
        end_time=end_time,
        status=AppointmentStatus.scheduled,
        no_show_risk=risk,
    )
    session.add(appt)
    await session.flush()
    await _log_reminders(session, appt, risk, db_settings)
    await session.commit()
    await session.refresh(appt)
    return appt, "ok"


async def update_appointment_status(
    session: AsyncSession, appt_id: uuid.UUID, new_status: AppointmentStatus
) -> Appointment | None:
    result = await session.execute(select(Appointment).where(Appointment.id == appt_id))
    appt = result.scalar_one_or_none()
    if appt is None:
        return None
    appt.status = new_status
    await session.commit()
    await session.refresh(appt)
    return appt


async def list_waitlist(
    session: AsyncSession,
    provider_id: uuid.UUID | None = None,
    status: WaitlistStatus | None = None,
) -> list[WaitlistEntry]:
    q = select(WaitlistEntry)
    if provider_id:
        q = q.where(WaitlistEntry.provider_id == provider_id)
    if status:
        q = q.where(WaitlistEntry.status == status)
    result = await session.execute(q)
    return list(result.scalars().all())


async def create_waitlist_entry(session: AsyncSession, data: WaitlistEntryCreate) -> WaitlistEntry:
    entry = WaitlistEntry(
        id=uuid.uuid4(),
        patient_uuid=data.patient_uuid,
        provider_id=data.provider_id,
        visit_type_id=data.visit_type_id,
        priority=data.priority,
        earliest_window=data.earliest_window,
        latest_window=data.latest_window,
        status=WaitlistStatus.waiting,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def manual_offer_slot(
    session: AsyncSession, entry_id: uuid.UUID
) -> tuple["WaitlistEntry | None", str]:
    result = await session.execute(select(WaitlistEntry).where(WaitlistEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if entry is None:
        return None, "not_found"
    if entry.status != WaitlistStatus.waiting:
        return None, "not_waiting"
    start = await find_next_available(session, entry.provider_id, entry.visit_type_id)
    if start is None:
        return None, "no_slot"
    vt = await get_visit_type(session, entry.visit_type_id)
    end = start + timedelta(minutes=vt.duration_minutes)
    entry.status = WaitlistStatus.offered
    entry.offered_at = datetime.now(UTC)
    entry.offered_slot_start = start
    entry.offered_slot_end = end
    await session.commit()
    await session.refresh(entry)
    return entry, "ok"


async def get_or_create_settings(session: AsyncSession) -> PracticeSettings:
    result = await session.execute(select(PracticeSettings).where(PracticeSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = PracticeSettings(id=1)
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    return settings


async def update_settings(session: AsyncSession, data: PracticeSettingsUpdate) -> PracticeSettings:
    settings = await get_or_create_settings(session)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(settings, field, value)
    await session.commit()
    await session.refresh(settings)
    return settings


async def create_schedule_block(session: AsyncSession, data: ScheduleBlockCreate) -> ScheduleBlock:
    block = ScheduleBlock(
        id=uuid.uuid4(),
        provider_id=data.provider_id,
        start_date=data.start_date,
        end_date=data.end_date,
        reason=data.reason,
    )
    session.add(block)
    await session.commit()
    await session.refresh(block)
    return block


async def list_schedule_blocks(
    session: AsyncSession, provider_id: uuid.UUID | None = None
) -> list[ScheduleBlock]:
    q = select(ScheduleBlock).order_by(ScheduleBlock.start_date)
    if provider_id is not None:
        q = q.where(
            or_(
                ScheduleBlock.provider_id == provider_id,
                ScheduleBlock.provider_id.is_(None),
            )
        )
    result = await session.execute(q)
    return list(result.scalars().all())


async def delete_schedule_block(session: AsyncSession, block_id: uuid.UUID) -> bool:
    result = await session.execute(select(ScheduleBlock).where(ScheduleBlock.id == block_id))
    block = result.scalar_one_or_none()
    if block is None:
        return False
    await session.delete(block)
    await session.commit()
    return True


async def get_outreach_log(session: AsyncSession, limit: int = 100) -> list[dict]:
    events: list[dict] = []

    # Waitlist offer events (any entry that was ever offered)
    wl_rows = (
        await session.execute(
            select(WaitlistEntry, Provider, VisitType)
            .join(Provider, Provider.id == WaitlistEntry.provider_id)
            .join(VisitType, VisitType.id == WaitlistEntry.visit_type_id)
            .where(WaitlistEntry.offered_at.isnot(None))
        )
    ).all()

    for entry, prov, vt in wl_rows:
        slot_str = (
            entry.offered_slot_start.strftime("%b %d at %H:%M")
            if entry.offered_slot_start
            else "TBD"
        )
        events.append(
            {
                "id": f"offer-{entry.id}",
                "at": entry.offered_at,
                "patient_uuid": entry.patient_uuid,
                "event_type": "offer_sent",
                "message_preview": (
                    f"Hi, a slot opened with {prov.name} on {slot_str} for your {vt.name}. "
                    f"Reply YES to confirm or NO to pass. Offer expires in 30 min."
                ),
                "status": entry.status.value,
                "slot_time": entry.offered_slot_start,
                "provider_name": prov.name,
                "visit_type_name": vt.name,
            }
        )

    # Appointment reminder events
    rem_rows = (
        await session.execute(
            select(ReminderLog, Appointment, VisitType, Provider)
            .join(Appointment, Appointment.id == ReminderLog.appointment_id)
            .join(VisitType, VisitType.id == Appointment.visit_type_id)
            .join(Provider, Provider.id == Appointment.provider_id)
        )
    ).all()

    for rem, appt, vt, prov in rem_rows:
        slot_str = appt.start_time.strftime("%b %d at %H:%M") if appt.start_time else "TBD"
        if rem.message_type == ReminderType.standard:
            event_type = "reminder_queued"
            preview = (
                f"Reminder: your {vt.name} with {prov.name} is on {slot_str}. "
                f"Reply CONFIRM to confirm attendance."
            )
        elif rem.message_type == ReminderType.followup:
            event_type = "reminder_followup"
            preview = (
                f"Follow-up: please confirm your {vt.name} with {prov.name} on {slot_str}. "
                f"Contact us if you need to reschedule."
            )
        else:
            event_type = "follow_up_created"
            preview = (
                f"Staff follow-up: high outreach flag for {vt.name} with {prov.name} on {slot_str}. "
                f"Please call the patient directly."
            )
        events.append(
            {
                "id": f"rem-{rem.id}",
                "at": rem.sent_at,
                "patient_uuid": appt.patient_uuid,
                "event_type": event_type,
                "message_preview": preview,
                "status": "queued",
                "slot_time": appt.start_time,
                "provider_name": prov.name,
                "visit_type_name": vt.name,
            }
        )

    events.sort(key=lambda e: e["at"], reverse=True)
    return events[:limit]


async def is_date_blocked(session: AsyncSession, provider_id: uuid.UUID, dt: date) -> bool:
    result = await session.execute(
        select(ScheduleBlock).where(
            and_(
                or_(
                    ScheduleBlock.provider_id == provider_id,
                    ScheduleBlock.provider_id.is_(None),
                ),
                ScheduleBlock.start_date <= dt,
                ScheduleBlock.end_date >= dt,
            )
        )
    )
    return result.scalar_one_or_none() is not None


async def find_next_available(
    session: AsyncSession,
    provider_id: uuid.UUID,
    visit_type_id: uuid.UUID,
    after: datetime | None = None,
    tz_offset_minutes: int = 0,
) -> datetime | None:
    vt = await get_visit_type(session, visit_type_id)
    if vt is None:
        return None

    settings = await get_or_create_settings(session)
    duration = timedelta(minutes=vt.duration_minutes)
    now = after or datetime.now(UTC)
    horizon = now + timedelta(days=60)

    offset_hours = tz_offset_minutes // 60
    utc_start = max(0, min(23, settings.work_start_hour + offset_hours))
    utc_end = max(1, min(24, settings.work_end_hour + offset_hours))

    # Prefetch all schedule blocks for this provider in one query
    blocks_result = await session.execute(
        select(ScheduleBlock).where(
            and_(
                or_(
                    ScheduleBlock.provider_id == provider_id,
                    ScheduleBlock.provider_id.is_(None),
                ),
                ScheduleBlock.end_date >= now.date(),
                ScheduleBlock.start_date <= horizon.date(),
            )
        )
    )
    blocks = blocks_result.scalars().all()

    def _is_blocked(dt: date) -> bool:
        return any(b.start_date <= dt <= b.end_date for b in blocks)

    # Prefetch all active appointments for this provider in one query
    buffer = timedelta(minutes=settings.buffer_minutes)
    appts_result = await session.execute(
        select(Appointment).where(
            and_(
                Appointment.provider_id == provider_id,
                Appointment.status != AppointmentStatus.cancelled,
                Appointment.start_time < horizon,
                Appointment.end_time > now,
            )
        )
    )
    appts = [(a.start_time, a.end_time) for a in appts_result.scalars().all()]

    def _has_overlap_local(start: datetime, end: datetime) -> bool:
        return any(a_start < end and a_end + buffer > start for a_start, a_end in appts)

    # Round up to next slot boundary
    step_mins = vt.duration_minutes + settings.buffer_minutes
    candidate = now.replace(second=0, microsecond=0)
    remainder = candidate.minute % step_mins if step_mins else 0
    if remainder:
        candidate += timedelta(minutes=step_mins - remainder)
    elif now.second or now.microsecond:
        candidate += timedelta(minutes=step_mins)

    def _next_day_start(dt: datetime) -> datetime:
        return datetime(dt.year, dt.month, dt.day, utc_start, 0, tzinfo=dt.tzinfo) + timedelta(days=1)

    for _ in range(60 * 24):
        slot_date = candidate.date()

        if _is_blocked(slot_date):
            candidate = _next_day_start(candidate)
            continue

        if candidate.hour < utc_start:
            candidate = candidate.replace(hour=utc_start, minute=0)
            continue

        end_candidate = candidate + duration
        if (
            end_candidate.date() > slot_date
            or end_candidate.hour > utc_end
            or (end_candidate.hour == utc_end and end_candidate.minute > 0)
        ):
            candidate = _next_day_start(candidate)
            continue

        if not _has_overlap_local(candidate, end_candidate):
            return candidate

        candidate += timedelta(minutes=step_mins)

    return None


async def get_dashboard_metrics(session: AsyncSession, days: int = 30) -> dict:
    cutoff = datetime.now(UTC) - timedelta(days=days)

    total_q = await session.execute(
        select(func.count()).where(
            and_(
                Appointment.created_at >= cutoff,
                Appointment.status.in_([AppointmentStatus.completed, AppointmentStatus.scheduled]),
            )
        )
    )
    total = total_q.scalar_one()

    completed_q = await session.execute(
        select(func.count()).where(
            and_(
                Appointment.created_at >= cutoff,
                Appointment.status == AppointmentStatus.completed,
            )
        )
    )
    completed = completed_q.scalar_one()

    booked_q = await session.execute(
        select(func.count()).where(
            and_(
                Appointment.created_at >= cutoff,
                Appointment.status.in_([AppointmentStatus.completed, AppointmentStatus.no_show]),
            )
        )
    )
    booked = booked_q.scalar_one()

    no_show_q = await session.execute(
        select(func.count()).where(
            and_(
                Appointment.created_at >= cutoff,
                Appointment.status == AppointmentStatus.no_show,
            )
        )
    )
    no_shows = no_show_q.scalar_one()

    recovered_q = await session.execute(
        select(func.count()).where(WaitlistEntry.status == WaitlistStatus.booked)
    )
    recovered = recovered_q.scalar_one()

    return {
        "fill_rate": completed / total if total > 0 else 0.0,
        "no_show_rate": no_shows / booked if booked > 0 else 0.0,
        "slots_recovered": recovered,
        "days": days,
    }
