import uuid

from pydantic import BaseModel, Field


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


class AskRequest(BaseModel):
    q: str = Field(..., min_length=2, description="Natural-language question")
    k: int | None = Field(None, ge=1, le=20)


class ProtocolAnswerResponse(BaseModel):
    """A grounded answer plus the exact passages it was generated from."""

    query: str
    answer: str | None
    passages: list[PassageResponse]
    model: str | None = None
    # False when no API key is configured. The passages are still returned, so
    # the caller degrades to plain retrieval rather than failing.
    generated: bool = True


class PatientAnswerResponse(ProtocolAnswerResponse):
    """
    Patient-scoped generation. Carries the UUID only — never a name.

    sent_to_external_model records what actually happened for this request, so
    the UI can state it rather than assert it. See config.patient_generation_enabled.
    """

    patient_uuid: uuid.UUID
    audit_logged: bool = True
    sent_to_external_model: bool = False
