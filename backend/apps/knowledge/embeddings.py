"""Embedding provider abstraction.

* ``openai``  — text-embedding-3-small (1536 dims). Needs OPENAI_API_KEY.
* ``hashing`` — local, deterministic feature-hashing embedder (no network, no key).
  Lexical rather than semantic, but good enough for development, tests and demos.

The configured provider is EMBEDDING_PROVIDER ("auto" picks openai when a key is
set, else hashing). Each chunk records the model id it was embedded with.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from functools import lru_cache
from typing import Protocol

from django.conf import settings

from apps.knowledge.models import EMBEDDING_DIMENSIONS


class EmbeddingError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    model_id: str

    def embed(self, texts: list[str]) -> tuple[list[list[float]], int]:
        """Return (vectors, tokens_used)."""


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "it",
        "this",
        "that",
        "with",
        "as",
        "at",
        "by",
        "from",
        "how",
        "do",
        "does",
        "i",
        "you",
        "we",
        "your",
        "my",
        "our",
        "can",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "would",
        "should",
        "could",
    ]
)


class HashingEmbeddings:
    model_id = "hashing-v1"

    def _tokens(self, text: str) -> list[str]:
        words = [w for w in _TOKEN_RE.findall(text.lower()) if w not in _STOPWORDS]
        stems = [w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words]
        return stems + [f"{a}_{b}" for a, b in itertools.pairwise(stems)]

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * EMBEDDING_DIMENSIONS
        for token in self._tokens(text):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % EMBEDDING_DIMENSIONS
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[index] += sign * (2.0 if "_" in token else 1.0)
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            vec[0] = 1.0
            return vec
        return [v / norm for v in vec]

    def embed(self, texts: list[str]) -> tuple[list[list[float]], int]:
        return [self._vector(t) for t in texts], sum(len(t) // 4 for t in texts)


class OpenAIEmbeddings:
    model_id = "openai:text-embedding-3-small"
    _model = "text-embedding-3-small"
    _batch = 96

    def __init__(self, api_key: str) -> None:
        import openai

        self._client = openai.OpenAI(api_key=api_key, timeout=settings.AI_REQUEST_TIMEOUT_SECONDS, max_retries=2)

    def embed(self, texts: list[str]) -> tuple[list[list[float]], int]:
        import openai

        vectors: list[list[float]] = []
        tokens = 0
        for start in range(0, len(texts), self._batch):
            batch = texts[start : start + self._batch]
            try:
                result = self._client.embeddings.create(model=self._model, input=batch)
            except openai.APIError as exc:
                raise EmbeddingError(f"OpenAI embeddings failed: {exc.__class__.__name__}") from exc
            vectors.extend(item.embedding for item in sorted(result.data, key=lambda d: d.index))
            tokens += result.usage.total_tokens
        return vectors, tokens


@lru_cache(maxsize=1)
def get_embedder() -> EmbeddingProvider:
    choice = settings.EMBEDDING_PROVIDER
    if choice == "auto":
        choice = "openai" if settings.OPENAI_API_KEY else "hashing"
    if choice == "openai":
        if not settings.OPENAI_API_KEY:
            raise EmbeddingError("EMBEDDING_PROVIDER=openai but OPENAI_API_KEY is not set.")
        return OpenAIEmbeddings(settings.OPENAI_API_KEY)
    return HashingEmbeddings()
