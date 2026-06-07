import uuid
from datetime import date, datetime, time

from pydantic import BaseModel

from app.scheduling.models import AppointmentStatus, WaitlistStatus


class ProviderCreate(BaseModel):
    name: str
    specialty: str | None = None


class ProviderResponse(BaseModel):
    id: uuid.UUID
    name: str
    specialty: str | None
    is_active: bool

    model_config = {"from_attributes": True}


class VisitTypeCreate(BaseModel):
    name: str
    duration_minutes: int
    is_new_patient: bool = False


class VisitTypeResponse(BaseModel):
    id: uuid.UUID
    name: str
    duration_minutes: int
    is_new_patient: bool

    model_config = {"from_attributes": True}


class AppointmentCreate(BaseModel):
    provider_id: uuid.UUID
    patient_uuid: uuid.UUID
    visit_type_id: uuid.UUID
    start_time: datetime


class AppointmentResponse(BaseModel):
    id: uuid.UUID
    provider_id: uuid.UUID
    patient_uuid: uuid.UUID
    visit_type_id: uuid.UUID
    start_time: datetime
    end_time: datetime
    status: AppointmentStatus
    no_show_risk: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class WaitlistEntryCreate(BaseModel):
    patient_uuid: uuid.UUID
    provider_id: uuid.UUID
    visit_type_id: uuid.UUID
    priority: int = 0
    earliest_window: time | None = None
    latest_window: time | None = None


class WaitlistEntryResponse(BaseModel):
    id: uuid.UUID
    patient_uuid: uuid.UUID
    provider_id: uuid.UUID
    visit_type_id: uuid.UUID
    priority: int
    requested_at: datetime
    earliest_window: time | None
    latest_window: time | None
    status: WaitlistStatus
    decline_count: int
    offered_at: datetime | None
    offered_slot_start: datetime | None
    offered_slot_end: datetime | None

    model_config = {"from_attributes": True}


class DashboardMetrics(BaseModel):
    fill_rate: float
    no_show_rate: float
    slots_recovered: int
    days: int


class RiskResponse(BaseModel):
    patient_uuid: uuid.UUID
    score: float | None
    bucket: str
    based_on: int


class ReminderLogResponse(BaseModel):
    id: uuid.UUID
    appointment_id: uuid.UUID
    sent_at: datetime
    channel: str
    message_type: str

    model_config = {"from_attributes": True}


class ScheduleBlockCreate(BaseModel):
    provider_id: uuid.UUID | None = None
    start_date: date
    end_date: date
    reason: str | None = None


class ScheduleBlockResponse(BaseModel):
    id: uuid.UUID
    provider_id: uuid.UUID | None
    start_date: date
    end_date: date
    reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class NextAvailableResponse(BaseModel):
    provider_id: uuid.UUID
    visit_type_id: uuid.UUID
    start_time: datetime
    end_time: datetime


class OutreachEventResponse(BaseModel):
    id: str
    at: datetime
    patient_uuid: uuid.UUID
    event_type: str
    message_preview: str
    status: str
    slot_time: datetime | None
    provider_name: str | None
    visit_type_name: str | None


class PracticeSettingsResponse(BaseModel):
    matcher_w1: float
    matcher_w2: float
    matcher_w3: float
    hold_window_minutes: int
    risk_low_threshold: float
    risk_high_threshold: float
    work_start_hour: int
    work_end_hour: int
    buffer_minutes: int

    model_config = {"from_attributes": True}


class PracticeSettingsUpdate(BaseModel):
    matcher_w1: float | None = None
    matcher_w2: float | None = None
    matcher_w3: float | None = None
    hold_window_minutes: int | None = None
    risk_low_threshold: float | None = None
    risk_high_threshold: float | None = None
    work_start_hour: int | None = None
    work_end_hour: int | None = None
    buffer_minutes: int | None = None


class MLPredictRequest(BaseModel):
    age: int
    gender: int  # 1 = Female, 0 = Male (matches Kaggle encoding)
    scholarship: int = 0
    hipertension: int = 0
    diabetes: int = 0
    alcoholism: int = 0
    handcap: int = 0
    sms_received: int = 0
    wait_days: int = 0


class MLPredictResponse(BaseModel):
    probability: float
    bucket: str
    note: str


class MLRiskResponse(BaseModel):
    patient_uuid: uuid.UUID
    probability: float
    bucket: str
    note: str
    features_used: dict
    wait_days: int
