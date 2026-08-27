"""
Document chunking and de-identification.

De-identification runs at ingest, not at query time, so plaintext names never
reach the vector store in the first place. A chunk that was never written
cannot leak.
"""

from __future__ import annotations

import re
import uuid

# Splits on markdown headings so a chunk keeps its section context.
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)


def chunk_markdown(text: str, max_chars: int = 1200) -> list[tuple[str, str]]:
    """
    Split markdown into (section_title, content) pairs.

    Sections longer than max_chars are broken on paragraph boundaries so a
    chunk never splits mid-sentence.
    """
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("", part) for part in _split_long("", text.strip(), max_chars)]

    chunks: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            chunks.extend((title, part) for part in _split_long(title, body, max_chars))
    return chunks


def _split_long(title: str, body: str, max_chars: int) -> list[str]:
    if len(body) <= max_chars:
        return [body] if body else []

    parts: list[str] = []
    current = ""
    for para in body.split("\n\n"):
        if current and len(current) + len(para) + 2 > max_chars:
            parts.append(current.strip())
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current.strip():
        parts.append(current.strip())
    return parts


def deidentify(text: str, patient_uuid: uuid.UUID, names: list[str]) -> str:
    """
    Replace known patient identifiers with the UUID token.

    `names` comes from the identity record, so this is targeted replacement
    rather than a general-purpose PHI scrubber. It is deliberately narrow: a
    statistical de-identifier that silently misses a name would be worse than
    one whose limits are obvious. Free-text notes from a real EHR would need
    a validated scrubber before they could go through here — which is one
    reason this project stays on synthetic documents.
    """
    token = f"[patient:{patient_uuid}]"
    out = text
    for name in sorted((n for n in names if n and len(n) > 2), key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(name)}\b", token, out, flags=re.IGNORECASE)
    # Given/family names are replaced independently, so "Jane Doe" leaves two
    # adjacent identical tokens. Collapse runs into one -- purely cosmetic, and
    # safe because everything being merged is already redacted.
    escaped = re.escape(token)
    return re.sub(rf"{escaped}(?:\s+{escaped})+", token, out)
