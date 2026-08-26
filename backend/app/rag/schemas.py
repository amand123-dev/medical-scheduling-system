import uuid

from pydantic import BaseModel


class PassageResponse(BaseModel):
    content: str
    source: str
    title: str
    chunk_index: int
    score: float


class ProtocolSearchResponse(BaseModel):
    query: str
    passages: list[PassageResponse]


class PatientContextResponse(BaseModel):
    """Patient-scoped retrieval. Carries the UUID only — never a name."""

    patient_uuid: uuid.UUID
    query: str
    passages: list[PassageResponse]
    audit_logged: bool = True
