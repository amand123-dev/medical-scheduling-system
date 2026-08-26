import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.config import settings as app_settings
from app.database import get_session
from app.rag import retrieval
from app.rag.schemas import (
    PassageResponse,
    PatientContextResponse,
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
