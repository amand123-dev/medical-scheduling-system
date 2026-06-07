import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class PatientCreate(BaseModel):
    first_name: str
    last_name: str
    dob: str
    phone: str
    email: EmailStr


class PatientUUIDResponse(BaseModel):
    patient_uuid: uuid.UUID


class PatientIdentityResponse(BaseModel):
    patient_uuid: uuid.UUID
    first_name: str
    last_name: str
    dob: str
    phone: str
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AccessLogEntry(BaseModel):
    id: uuid.UUID
    patient_uuid: uuid.UUID
    accessed_by: uuid.UUID
    accessed_by_username: str | None = None
    action: str
    at: datetime

    model_config = {"from_attributes": True}
