import uuid
from datetime import date, datetime, time
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Time,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StaffRole(StrEnum):
    admin = "admin"
    provider = "provider"
    front_desk = "front_desk"


class AppointmentStatus(StrEnum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


class WaitlistStatus(StrEnum):
    waiting = "waiting"
    offered = "offered"
    booked = "booked"
    declined = "declined"
    expired = "expired"


class ReminderChannel(StrEnum):
    sms = "sms"
    email = "email"
    call = "call"


class ReminderType(StrEnum):
    standard = "standard"
    followup = "followup"
    call_requested = "call_requested"


class Provider(Base):
    __tablename__ = "provider"
    __table_args__ = {"schema": "operational"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150))
    specialty: Mapped[str] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Comma-separated weekday numbers 0=Mon…6=Sun. NULL means practice default (Mon–Fri).
    work_days: Mapped[str | None] = mapped_column(String(20), nullable=True)
    work_start_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    work_end_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)

    appointments: Mapped[list["Appointment"]] = relationship(back_populates="provider")
    waitlist_entries: Mapped[list["WaitlistEntry"]] = relationship(back_populates="provider")


class VisitType(Base):
    __tablename__ = "visit_type"
    __table_args__ = {"schema": "operational"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    is_new_patient: Mapped[bool] = mapped_column(Boolean, default=False)

    appointments: Mapped[list["Appointment"]] = relationship(back_populates="visit_type")
    waitlist_entries: Mapped[list["WaitlistEntry"]] = relationship(back_populates="visit_type")


class StaffUser(Base):
    __tablename__ = "staff_user"
    __table_args__ = {"schema": "operational"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(200))
    role: Mapped[StaffRole] = mapped_column(Enum(StaffRole, schema="operational"))
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operational.provider.id", ondelete="SET NULL"),
        nullable=True,
    )


class Appointment(Base):
    __tablename__ = "appointment"
    __table_args__ = {"schema": "operational"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operational.provider.id", ondelete="CASCADE")
    )
    patient_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    visit_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operational.visit_type.id", ondelete="RESTRICT")
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, schema="operational"), default=AppointmentStatus.scheduled
    )
    no_show_risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    provider: Mapped["Provider"] = relationship(back_populates="appointments")
    visit_type: Mapped["VisitType"] = relationship(back_populates="appointments")
    reminders: Mapped[list["ReminderLog"]] = relationship(back_populates="appointment")


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entry"
    __table_args__ = {"schema": "operational"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operational.provider.id", ondelete="CASCADE")
    )
    visit_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operational.visit_type.id", ondelete="RESTRICT")
    )
    priority: Mapped[int] = mapped_column(Integer, default=0)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    earliest_window: Mapped[time | None] = mapped_column(Time, nullable=True)
    latest_window: Mapped[time | None] = mapped_column(Time, nullable=True)
    status: Mapped[WaitlistStatus] = mapped_column(
        Enum(WaitlistStatus, schema="operational"), default=WaitlistStatus.waiting
    )
    decline_count: Mapped[int] = mapped_column(Integer, default=0)
    offered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offered_slot_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    offered_slot_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    offer_token: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, unique=True
    )

    provider: Mapped["Provider"] = relationship(back_populates="waitlist_entries")
    visit_type: Mapped["VisitType"] = relationship(back_populates="waitlist_entries")


class ReminderLog(Base):
    __tablename__ = "reminder_log"
    __table_args__ = {"schema": "operational"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operational.appointment.id", ondelete="CASCADE")
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    channel: Mapped[ReminderChannel] = mapped_column(Enum(ReminderChannel, schema="operational"))
    message_type: Mapped[ReminderType] = mapped_column(Enum(ReminderType, schema="operational"))

    appointment: Mapped["Appointment"] = relationship(back_populates="reminders")


class ScheduleBlock(Base):
    __tablename__ = "schedule_block"
    __table_args__ = {"schema": "operational"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operational.provider.id", ondelete="CASCADE"),
        nullable=True,
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    provider: Mapped["Provider | None"] = relationship()


class PracticeSettings(Base):
    __tablename__ = "practice_settings"
    __table_args__ = {"schema": "operational"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    matcher_w1: Mapped[float] = mapped_column(Float, default=1.0)
    matcher_w2: Mapped[float] = mapped_column(Float, default=0.5)
    matcher_w3: Mapped[float] = mapped_column(Float, default=0.3)
    hold_window_minutes: Mapped[int] = mapped_column(Integer, default=30)
    risk_low_threshold: Mapped[float] = mapped_column(Float, default=0.2)
    risk_high_threshold: Mapped[float] = mapped_column(Float, default=0.5)
    work_start_hour: Mapped[int] = mapped_column(Integer, default=8)
    work_end_hour: Mapped[int] = mapped_column(Integer, default=17)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=0)


class PatientAccount(Base):
    __tablename__ = "patient_account"
    __table_args__ = {"schema": "operational"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
