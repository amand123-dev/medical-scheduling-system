"""
Vector retrieval over the two corpora.

Protocol search is unprivileged. Patient-document search is not: it resolves
information about an identified person, so it takes the caller's staff id,
enforces role, and writes identity_access_log — the same contract as a name
lookup. A chatbot that retrieves eight chunks about a patient has performed an
identity-resolving operation, and the audit trail has to show it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import IdentityAccessLog
from app.rag.embeddings import cosine_similarity, get_embedder
from app.rag.models import PatientDocumentChunk, ProtocolChunk

RAG_RETRIEVAL_ACTION = "rag_retrieval"
RAG_GENERATION_ACTION = "rag_generation"


@dataclass
class Passage:
    """A retrieved chunk with its citation metadata."""

    content: str
    source: str
    title: str
    chunk_index: int
    score: float

    def as_dict(self) -> dict:
        return {
            "content": self.content,
            "source": self.source,
            "title": self.title,
            "chunk_index": self.chunk_index,
            "score": round(self.score, 4),
        }


def _uses_pgvector(session: AsyncSession) -> bool:
    return session.bind is not None and session.bind.dialect.name == "postgresql"


async def search_protocols(session: AsyncSession, query: str, k: int = 5) -> list[Passage]:
    """Similarity search over clinic protocols. No PHI, so no audit entry."""
    vector = get_embedder().embed([query])[0]

    if _uses_pgvector(session):
        stmt = (
            select(ProtocolChunk, ProtocolChunk.embedding.cosine_distance(vector).label("distance"))
            .order_by("distance")
            .limit(k)
        )
        rows = (await session.execute(stmt)).all()
        return [
            Passage(
                content=row[0].content,
                source=row[0].source_doc,
                title=row[0].title,
                chunk_index=row[0].chunk_index,
                score=1.0 - float(row[1]),
            )
            for row in rows
        ]

    # SQLite (tests): no vector operators, so rank in Python.
    chunks = (await session.execute(select(ProtocolChunk))).scalars().all()
    scored = [
        Passage(
            content=c.content,
            source=c.source_doc,
            title=c.title,
            chunk_index=c.chunk_index,
            score=cosine_similarity(vector, c.embedding),
        )
        for c in chunks
    ]
    scored.sort(key=lambda p: p.score, reverse=True)
    return scored[:k]


async def search_patient_documents(
    session: AsyncSession,
    patient_uuid: uuid.UUID,
    query: str,
    accessed_by: uuid.UUID,
    k: int = 5,
) -> list[Passage]:
    """
    Similarity search scoped to one patient.

    patient_uuid is a hard pre-filter in the SQL, not a post-filter on the
    result set — similarity must never be the thing standing between one
    patient's chart and another's. Writes identity_access_log before
    returning.
    """
    vector = get_embedder().embed([query])[0]

    if _uses_pgvector(session):
        stmt = (
            select(
                PatientDocumentChunk,
                PatientDocumentChunk.embedding.cosine_distance(vector).label("distance"),
            )
            .where(PatientDocumentChunk.patient_uuid == patient_uuid)
            .order_by("distance")
            .limit(k)
        )
        rows = (await session.execute(stmt)).all()
        passages = [
            Passage(
                content=row[0].content,
                source=row[0].source_doc_id,
                title=row[0].doc_type,
                chunk_index=row[0].chunk_index,
                score=1.0 - float(row[1]),
            )
            for row in rows
        ]
    else:
        chunks = (
            (
                await session.execute(
                    select(PatientDocumentChunk).where(
                        PatientDocumentChunk.patient_uuid == patient_uuid
                    )
                )
            )
            .scalars()
            .all()
        )
        scored = [
            Passage(
                content=c.content,
                source=c.source_doc_id,
                title=c.doc_type,
                chunk_index=c.chunk_index,
                score=cosine_similarity(vector, c.embedding),
            )
            for c in chunks
        ]
        scored.sort(key=lambda p: p.score, reverse=True)
        passages = scored[:k]

    session.add(
        IdentityAccessLog(
            patient_uuid=patient_uuid,
            accessed_by=accessed_by,
            action=RAG_RETRIEVAL_ACTION,
        )
    )
    await session.commit()
    return passages


async def log_generation_access(
    session: AsyncSession, patient_uuid: uuid.UUID, accessed_by: uuid.UUID
) -> None:
    """
    Record that a patient's passages were sent to an external model.

    Deliberately a separate action from rag_retrieval: reading a chart in the
    UI and shipping it to a third party are different events, and an audit
    trail that cannot tell them apart is not much of an audit trail.
    """
    session.add(
        IdentityAccessLog(
            patient_uuid=patient_uuid,
            accessed_by=accessed_by,
            action=RAG_GENERATION_ACTION,
        )
    )
    await session.commit()
