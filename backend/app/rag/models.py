"""
Vector-store tables for retrieval.

The corpus is deliberately split across the two schemas along the same
boundary as the rest of the app:

  operational.protocol_chunk        — clinic protocols and policies. No PHI,
                                      readable by any authenticated staff user.
  identity.patient_document_chunk   — patient-scoped visit summaries. Chunks are
                                      de-identified at ingest and keyed by
                                      patient_uuid; reads are role-gated and
                                      written to identity_access_log.

Storing patient vectors in the identity schema is the point: embeddings of
clinical text are themselves PHI, so they live inside the same trust boundary
as the names they were derived from, not in a separate vector service.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.rag.embeddings import EMBEDDING_DIMENSIONS

try:
    from pgvector.sqlalchemy import Vector

    _EMBEDDING_TYPE = Vector(EMBEDDING_DIMENSIONS).with_variant(JSON(), "sqlite")
except ImportError:  # pragma: no cover - pgvector is a hard dep in deployment
    _EMBEDDING_TYPE = JSON()


class ProtocolChunk(Base):
    """A chunk of a clinic protocol or policy document. Contains no PHI."""

    __tablename__ = "protocol_chunk"
    __table_args__ = {"schema": "operational"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_doc: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(_EMBEDDING_TYPE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PatientDocumentChunk(Base):
    """
    A chunk of a patient's visit summary, de-identified at ingest.

    `content` is expected to be tokenized already — names replaced with the
    patient's UUID by the ingest pipeline — so a leak of this table alone does
    not resolve to a person without also breaching the identity schema.
    """

    __tablename__ = "patient_document_chunk"
    __table_args__ = {"schema": "identity"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    source_doc_id: Mapped[str] = mapped_column(String(200))
    doc_type: Mapped[str] = mapped_column(String(100))
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(_EMBEDDING_TYPE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
