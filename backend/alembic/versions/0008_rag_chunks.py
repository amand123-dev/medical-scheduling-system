"""add pgvector chunk tables for protocol and patient-document retrieval

Creates the vector extension and two chunk tables, split across the two
schemas along the same trust boundary as the rest of the app:

  operational.protocol_chunk       — no PHI, readable by any staff role
  identity.patient_document_chunk  — patient-scoped, audit-logged reads

Embeddings of clinical text are themselves PHI, so the patient vectors live
inside the identity schema rather than in a separate vector service.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-26
"""

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# BAAI/bge-small-en-v1.5. Changing the model means re-embedding the corpus
# and altering these column widths.
EMBEDDING_DIMENSIONS = 384


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "protocol_chunk",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_doc", sa.String(200), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="operational",
    )

    op.create_table(
        "patient_document_chunk",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_uuid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_doc_id", sa.String(200), nullable=False),
        sa.Column("doc_type", sa.String(100), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="identity",
    )

    # patient_uuid is a hard pre-filter on every patient-scoped query, so it is
    # indexed independently of the vector index.
    op.create_index(
        "ix_patient_document_chunk_patient_uuid",
        "patient_document_chunk",
        ["patient_uuid"],
        schema="identity",
    )

    # HNSW over cosine distance. Built after ingest in a fresh database, but
    # created here so a re-seed does not need a manual step.
    op.execute(
        "CREATE INDEX ix_protocol_chunk_embedding ON operational.protocol_chunk "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX ix_patient_document_chunk_embedding ON identity.patient_document_chunk "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_table("patient_document_chunk", schema="identity")
    op.drop_table("protocol_chunk", schema="operational")
    # The vector extension is left in place; other objects may depend on it.
