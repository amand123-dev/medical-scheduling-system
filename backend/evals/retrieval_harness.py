"""
Stand up an ephemeral protocol index for the eval.

The point is to exercise the real code — app.rag.chunking, app.rag.ingest and
app.rag.search_protocols — rather than a parallel implementation that could
drift from what ships. Only the storage is swapped: an in-memory SQLite index,
so the eval runs without Postgres or pgvector.

Retrieval ranking differs from production in one way: Postgres ranks with an
HNSW index while SQLite ranks in Python. HNSW is approximate, so production
recall can be marginally lower than what this reports. Run with --database-url
against a seeded Postgres to measure the deployed path exactly.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.rag import ingest, retrieval

MEMORY_URL = "sqlite+aiosqlite:///:memory:"


def _strip_schemas(metadata) -> None:
    """SQLite has no schemas; flatten identity/operational so create_all works."""
    for table in metadata.tables.values():
        table.schema = None
        for col in table.columns:
            if hasattr(col.type, "schema"):
                col.type.schema = None
            if hasattr(col.type, "native_enum"):
                col.type.native_enum = False


@asynccontextmanager
async def protocol_index(
    corpus_dir: Path | None = None,
    database_url: str | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a session with the protocol corpus ingested."""
    url = database_url or MEMORY_URL
    engine = create_async_engine(url, echo=False)
    if url.startswith("sqlite"):
        _strip_schemas(Base.metadata)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            await ingest.ingest_protocol_dir(session, corpus_dir)
            yield session
    finally:
        await engine.dispose()


async def retrieve(session: AsyncSession, question: str, k: int) -> list[dict]:
    passages = await retrieval.search_protocols(session, question, k)
    return [p.as_dict() for p in passages]
