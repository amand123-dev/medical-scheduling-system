import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.config import settings as app_settings
from app.database import get_session
from app.rag import generation, retrieval
from app.rag.schemas import (
    AskRequest,
    PassageResponse,
    PatientAnswerResponse,
    PatientContextResponse,
    ProtocolAnswerResponse,
    ProtocolSearchResponse,
)
from app.scheduling.models import StaffRole, StaffUser

router = APIRouter(prefix="/rag", tags=["retrieval"])


@router.get("/protocols/search", response_model=ProtocolSearchResponse)
async def search_protocols(
    q: str = Query(..., min_length=2, description="Natural-language question"),
    k: int = Query(None, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(get_current_user),
):
    """Retrieve clinic protocol passages. Contains no PHI, so any staff role may call it."""
    passages = await retrieval.search_protocols(session, q, k or app_settings.rag_top_k)
    return ProtocolSearchResponse(
        query=q,
        passages=[PassageResponse(**p.as_dict()) for p in passages],
    )


@router.get("/patients/{patient_uuid}/context", response_model=PatientContextResponse)
async def patient_context(
    patient_uuid: uuid.UUID,
    q: str = Query(..., min_length=2),
    k: int = Query(None, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
    user: StaffUser = Depends(require_role(StaffRole.admin, StaffRole.provider)),
):
    """
    Retrieve passages from one patient's documents.

    This is an identity-resolving operation: it returns information about a
    specific person. It is role-gated like the reverse-lookup endpoint and
    writes identity_access_log on every call.
    """
    passages = await retrieval.search_patient_documents(
        session,
        patient_uuid=patient_uuid,
        query=q,
        accessed_by=user.id,
        k=k or app_settings.rag_top_k,
    )
    return PatientContextResponse(
        patient_uuid=patient_uuid,
        query=q,
        passages=[PassageResponse(**p.as_dict()) for p in passages],
    )


@router.post("/protocols/ask", response_model=ProtocolAnswerResponse)
async def ask_protocols(
    body: AskRequest,
    session: AsyncSession = Depends(get_session),
    _user: StaffUser = Depends(get_current_user),
):
    """
    Answer a question from clinic protocol passages.

    Protocol documents carry no PHI, so this is open to any staff role, same as
    the search endpoint it wraps.
    """
    if not app_settings.protocol_generation_enabled:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Protocol answering is disabled. Retrieval remains available at "
            "GET /rag/protocols/search.",
        )
    passages = await retrieval.search_protocols(session, body.q, body.k or app_settings.rag_top_k)
    client = generation.get_client()
    answer = await generation.answer(body.q, passages, client=client)
    return ProtocolAnswerResponse(
        query=body.q,
        answer=answer,
        passages=[PassageResponse(**p.as_dict()) for p in passages],
        model=app_settings.generation_model if client else None,
        generated=client is not None,
    )


@router.post("/patients/{patient_uuid}/ask", response_model=PatientAnswerResponse)
async def ask_patient_context(
    patient_uuid: uuid.UUID,
    body: AskRequest,
    session: AsyncSession = Depends(get_session),
    user: StaffUser = Depends(require_role(StaffRole.admin, StaffRole.provider)),
):
    """
    Summarise one patient's records in answer to a question.

    This is the only path in the system where patient-derived text leaves the
    process, which is why it ships disabled. De-identification here is
    data minimisation, not anonymisation: the [patient:<uuid>] token is
    reversible by anyone with database access, so the passages remain PHI. A
    production deployment would need a BAA with zero-retention terms before
    this is switched on — the code being ready is not the same as being
    permitted to run it.

    Role-gated and audit-logged identically to the retrieval endpoint; the
    generation step adds its own log row so the record distinguishes "staff
    read this chart" from "this chart was sent to a model".
    """
    if not app_settings.patient_generation_enabled:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Patient answering is disabled. Enable it only under a BAA with "
            "zero-retention terms; retrieval remains available at "
            "GET /rag/patients/{patient_uuid}/context.",
        )

    # Retrieval writes its own identity_access_log row and enforces the
    # patient_uuid pre-filter. Going through it keeps one code path for both.
    passages = await retrieval.search_patient_documents(
        session,
        patient_uuid=patient_uuid,
        query=body.q,
        accessed_by=user.id,
        k=body.k or app_settings.rag_top_k,
    )
    client = generation.get_client()
    answer = await generation.answer(
        body.q, passages, system=generation.PATIENT_SYSTEM, client=client
    )

    sent = client is not None and bool(passages)
    if sent:
        await retrieval.log_generation_access(session, patient_uuid, user.id)

    return PatientAnswerResponse(
        patient_uuid=patient_uuid,
        query=body.q,
        answer=answer,
        passages=[PassageResponse(**p.as_dict()) for p in passages],
        model=app_settings.generation_model if client else None,
        generated=client is not None,
        sent_to_external_model=sent,
    )
