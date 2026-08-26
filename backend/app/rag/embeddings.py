"""
Embedding providers.

Two implementations behind one interface:

  fastembed — ONNX-quantized BAAI/bge-small-en-v1.5, run locally on CPU. No
              PyTorch, no API key, and no text leaves the process. That last
              property is the point: patient-derived vectors never reach a
              third party, so the trust boundary the schema draws holds for
              the retrieval layer too.

  hashing   — deterministic offline fallback (hashing trick over word
              n-grams). Used by the test suite and by CI so neither needs a
              model download or network access. Retrieval quality is poor;
              it exists to exercise the pipeline, not to serve traffic.

Both emit unit-normalized vectors of EMBEDDING_DIMENSIONS floats, so cosine
similarity is a dot product and the two are interchangeable at the storage
layer.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Protocol

logger = logging.getLogger(__name__)

# BAAI/bge-small-en-v1.5. Changing this requires re-embedding the whole corpus
# and a migration to alter the vector column width.
EMBEDDING_DIMENSIONS = 384

FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"

_WORD_RE = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


class HashingEmbedder:
    """
    Deterministic, dependency-free embedder for tests.

    Hashes unigrams and bigrams into a fixed-width vector. Documents sharing
    vocabulary land near each other, which is enough to assert that ranking,
    filtering and audit behaviour are wired correctly.
    """

    name = "hashing"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        words = _WORD_RE.findall(text.lower())
        grams = words + [f"{a}_{b}" for a, b in zip(words, words[1:], strict=False)]
        vec = [0.0] * EMBEDDING_DIMENSIONS
        for gram in grams:
            digest = hashlib.blake2b(gram.encode(), digest_size=8).digest()
            slot = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[slot] += sign
        return _normalize(vec)


class FastEmbedEmbedder:
    """Local ONNX embeddings. Imports fastembed lazily so it stays optional."""

    name = "fastembed"

    def __init__(self) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=FASTEMBED_MODEL)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.embed(texts)]


_cached: Embedder | None = None


def get_embedder(provider: str | None = None) -> Embedder:
    """
    Return the configured embedder, cached across calls.

    Falls back to the hashing embedder when fastembed is not installed, so a
    missing optional dependency degrades retrieval quality instead of breaking
    the app — the same posture scorer/ml.py takes toward joblib.
    """
    global _cached
    if provider is None:
        from app.config import settings

        provider = settings.embedding_provider

    if _cached is not None and _cached.name == provider:
        return _cached

    if provider == "fastembed":
        try:
            _cached = FastEmbedEmbedder()
        except ImportError:
            # Loud, because the failure is otherwise invisible: retrieval keeps
            # working, just badly. This was silently degrading the eval baseline
            # until the harness reported which embedder it had actually used.
            logger.warning(
                "embedding_provider=%r but fastembed is not installed; falling back to "
                "the hashing embedder. Retrieval quality will be significantly worse. "
                "Install it with: pip install fastembed",
                provider,
            )
            _cached = HashingEmbedder()
    else:
        _cached = HashingEmbedder()
    return _cached


def cosine_similarity(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))
