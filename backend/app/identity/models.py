import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy_utils import StringEncryptedType
from sqlalchemy_utils.types.encrypted.encrypted_type import AesEngine

from app.config import settings
from app.database import Base


class EncryptedStr(StringEncryptedType):
    """AES-encrypted string column. Ciphertext is base64, so the DDL is TEXT."""

    impl = Text
    cache_ok = True


def _encrypted() -> EncryptedStr:
    return EncryptedStr(String, settings.encryption_key, AesEngine, "pkcs5")


class PatientIdentity(Base):
    __tablename__ = "patient_identity"
    __table_args__ = {"schema": "identity"}

    patient_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # PII at rest: AES-encrypted via SQLAlchemy type decorator. Encryption happens
    # on bind, decryption on load, so every access must go through the ORM —
    # raw SQL against these columns reads ciphertext.
    first_name: Mapped[str] = mapped_column(_encrypted())
    last_name: Mapped[str] = mapped_column(_encrypted())
    dob: Mapped[str] = mapped_column(_encrypted())
    phone: Mapped[str] = mapped_column(_encrypted())
    email: Mapped[str] = mapped_column(_encrypted())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdentityAccessLog(Base):
    __tablename__ = "identity_access_log"
    __table_args__ = {"schema": "identity"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    accessed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(50))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
