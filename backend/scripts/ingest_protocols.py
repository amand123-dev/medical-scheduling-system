"""
Embed the clinic protocol corpus into operational.protocol_chunk.

Run from backend/:  python scripts/ingest_protocols.py

Idempotent — re-ingesting replaces a document's chunks rather than duplicating
them, so this is safe to run on every deploy.
"""

import asyncio
import sys

sys.path.insert(0, ".")
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.rag.embeddings import get_embedder
from app.rag.ingest import PROTOCOL_DIR, ingest_protocol_dir


async def main() -> None:
    embedder = get_embedder()
    print(f"Embedding provider: {embedder.name}")
    if embedder.name == "hashing":
        print(
            "  WARNING: fastembed is not installed, so retrieval quality will be poor.\n"
            "  Install it with: pip install fastembed"
        )
    print(f"Reading protocols from {PROTOCOL_DIR}")

    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        counts = await ingest_protocol_dir(session)

    total = sum(counts.values())
    for name, count in counts.items():
        print(f"  {name:<40} {count:>3} chunks")
    print(f"Ingested {total} chunks from {len(counts)} documents.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
