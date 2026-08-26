"""encrypt PII columns in identity.patient_identity

Widens the PII columns to TEXT (base64 ciphertext is longer than the
plaintext it replaces) and encrypts any existing rows in place.

The encryption is AES via sqlalchemy_utils, so it cannot be expressed in
SQL — existing rows are read, encrypted in Python, and written back.

ENCRYPTION_KEY must be settled BEFORE this runs. Rotating it afterwards
leaves existing rows undecryptable; the only recovery is downgrade with
the old key in place, or a re-seed.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-26
"""

import sqlalchemy as sa
from sqlalchemy_utils.types.encrypted.encrypted_type import AesEngine, StringEncryptedType

from alembic import op
from app.config import settings

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

PII_COLUMNS = ("first_name", "last_name", "dob", "phone", "email")

# Original column widths, for downgrade.
ORIGINAL_WIDTHS = {
    "first_name": 100,
    "last_name": 100,
    "dob": 20,
    "phone": 30,
    "email": 254,
}


def _cipher() -> StringEncryptedType:
    return StringEncryptedType(sa.String, settings.encryption_key, AesEngine, "pkcs5")


def _rewrite_rows(conn, transform) -> None:
    """Apply `transform` to every PII value in the table, row by row."""
    rows = (
        conn.execute(
            sa.text(
                "SELECT patient_uuid, first_name, last_name, dob, phone, email "
                "FROM identity.patient_identity"
            )
        )
        .mappings()
        .all()
    )

    for row in rows:
        conn.execute(
            sa.text(
                "UPDATE identity.patient_identity SET "
                "first_name = :first_name, last_name = :last_name, dob = :dob, "
                "phone = :phone, email = :email "
                "WHERE patient_uuid = :patient_uuid"
            ),
            {
                "patient_uuid": row["patient_uuid"],
                **{col: transform(row[col]) for col in PII_COLUMNS},
            },
        )


def upgrade() -> None:
    conn = op.get_bind()

    for col in PII_COLUMNS:
        op.alter_column(
            "patient_identity",
            col,
            type_=sa.Text(),
            existing_nullable=False,
            schema="identity",
        )

    cipher = _cipher()
    _rewrite_rows(conn, lambda v: cipher.process_bind_param(v, conn.dialect))


def downgrade() -> None:
    conn = op.get_bind()

    cipher = _cipher()
    _rewrite_rows(conn, lambda v: cipher.process_result_value(v, conn.dialect))

    for col in PII_COLUMNS:
        op.alter_column(
            "patient_identity",
            col,
            type_=sa.String(ORIGINAL_WIDTHS[col]),
            existing_nullable=False,
            schema="identity",
        )
