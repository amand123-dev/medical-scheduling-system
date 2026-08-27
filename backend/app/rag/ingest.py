"""
Corpus ingest.

Protocol documents are read from data/protocols/*.md. Patient documents arrive
already de-identified — see chunking.deidentify — and are keyed by UUID.

Ingest is idempotent per source document: re-ingesting a file replaces its
chunks rather than duplicating them, so the seed script can be re-run.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.chunking import chunk_markdown
from app.rag.embeddings import get_embedder
from app.rag.models import PatientDocumentChunk, ProtocolChunk

PROTOCOL_DIR = Path(__file__).resolve().parents[2] / "data" / "protocols"


async def ingest_protocol_file(session: AsyncSession, path: Path) -> int:
    """Chunk, embed and store one protocol document. Returns the chunk count."""
    text = path.read_text()
    chunks = chunk_markdown(text)
    if not chunks:
        return 0

    await session.execute(delete(ProtocolChunk).where(ProtocolChunk.source_doc == path.name))

    embeddings = get_embedder().embed([f"{title}\n\n{body}" for title, body in chunks])
    for index, ((title, body), vector) in enumerate(zip(chunks, embeddings, strict=True)):
        session.add(
            ProtocolChunk(
                source_doc=path.name,
                title=title,
                chunk_index=index,
                content=body,
                embedding=vector,
            )
        )
    await session.commit()
    return len(chunks)


async def ingest_protocol_dir(session: AsyncSession, directory: Path | None = None) -> dict:
    """Ingest every markdown file in the protocol directory."""
    directory = directory or PROTOCOL_DIR
    counts: dict[str, int] = {}
    for path in sorted(directory.glob("*.md")):
        counts[path.name] = await ingest_protocol_file(session, path)
    return counts


async def ingest_patient_document(
    session: AsyncSession,
    patient_uuid: uuid.UUID,
    source_doc_id: str,
    doc_type: str,
    deidentified_text: str,
) -> int:
    """
    Store one already-de-identified patient document.

    This function does not de-identify; it expects text that has already been
    through chunking.deidentify. Keeping the two separate means the call site
    has to name the identity record it scrubbed against, rather than hoping a
    scrubber inside the writer catches everything.
    """
    chunks = chunk_markdown(deidentified_text)
    if not chunks:
        return 0

    await session.execute(
        delete(PatientDocumentChunk).where(PatientDocumentChunk.source_doc_id == source_doc_id)
    )

    embeddings = get_embedder().embed([f"{title}\n\n{body}" for title, body in chunks])
    for index, ((_title, body), vector) in enumerate(zip(chunks, embeddings, strict=True)):
        session.add(
            PatientDocumentChunk(
                patient_uuid=patient_uuid,
                source_doc_id=source_doc_id,
                doc_type=doc_type,
                chunk_index=index,
                content=body,
                embedding=vector,
            )
        )
    await session.commit()
    return len(chunks)
