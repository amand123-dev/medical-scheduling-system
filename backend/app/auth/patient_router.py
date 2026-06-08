import uuid

import bcrypt as _bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token, create_refresh_token
from app.auth.router import TokenResponse
from app.database import get_session
from app.scheduling.models import PatientAccount

router = APIRouter(prefix="/auth/patient", tags=["patient-auth"])


class PatientRegisterRequest(BaseModel):
    first_name: str
    last_name: str
    dob: str  # YYYY-MM-DD
    phone: str
    email: EmailStr
    password: str


class PatientLoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", response_model=TokenResponse, status_code=201)
async def patient_register(body: PatientRegisterRequest, session: AsyncSession = Depends(get_session)):
    # Check email not already taken
    existing = await session.execute(
        select(PatientAccount).where(PatientAccount.email == body.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    patient_uuid = uuid.uuid4()
    hashed = _bcrypt.hashpw(body.password.encode(), _bcrypt.gensalt()).decode()

    # Create identity record (patient self-creates their own PII)
    await session.execute(
        text(
            "INSERT INTO identity.patient_identity "
            "(patient_uuid, first_name, last_name, dob, phone, email) "
            "VALUES (:uuid, :first, :last, :dob, :phone, :email)"
        ),
        {
            "uuid": str(patient_uuid),
            "first": body.first_name,
            "last": body.last_name,
            "dob": body.dob,
            "phone": body.phone,
            "email": body.email,
        },
    )

    # Create patient account
    account = PatientAccount(
        id=uuid.uuid4(),
        patient_uuid=patient_uuid,
        email=body.email,
        hashed_password=hashed,
    )
    session.add(account)
    await session.commit()

    return TokenResponse(
        access_token=create_access_token(str(patient_uuid), "patient"),
        refresh_token=create_refresh_token(str(patient_uuid)),
    )


@router.post("/login", response_model=TokenResponse)
async def patient_login(body: PatientLoginRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(PatientAccount).where(PatientAccount.email == body.email)
    )
    account = result.scalar_one_or_none()
    if account is None or not _bcrypt.checkpw(body.password.encode(), account.hashed_password.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad credentials")

    return TokenResponse(
        access_token=create_access_token(str(account.patient_uuid), "patient"),
        refresh_token=create_refresh_token(str(account.patient_uuid)),
    )
