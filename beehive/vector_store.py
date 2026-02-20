from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Dict, List, Protocol, Tuple


class VectorStore(Protocol):
    def upsert(self, item_id: str, text: str) -> None:
        ...

    def search(self, query: str, limit: int = 5) -> list[str]:
        ...


def _hash_embedding(text: str, dim: int = 64) -> list[float]:
    """
    Deterministic lightweight embedding for local/dev use.
    """
    vec = [0.0] * dim
    for token in text.lower().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for idx in range(dim):
            vec[idx] += digest[idx % len(digest)] / 255.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


@dataclass
class InMemoryVectorStore:
    dim: int = 64

    def __post_init__(self) -> None:
        self._vectors: Dict[str, list[float]] = {}

    def upsert(self, item_id: str, text: str) -> None:
        self._vectors[item_id] = _hash_embedding(text, dim=self.dim)

    def search(self, query: str, limit: int = 5) -> list[str]:
        q = _hash_embedding(query, dim=self.dim)
        scored: List[Tuple[str, float]] = []
        for item_id, vec in self._vectors.items():
            scored.append((item_id, _dot(q, vec)))
        scored.sort(key=lambda row: row[1], reverse=True)
        return [item_id for item_id, _ in scored[:limit]]


@dataclass
class QdrantVectorStore:
    collection: str = "honeycomb_memory"
    url: str = "http://localhost:6333"
    dim: int = 64
    _ready: bool = False

    def __post_init__(self) -> None:
        self._fallback = InMemoryVectorStore(dim=self.dim)
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as qdrant_models

            self._qdrant_models = qdrant_models
            self._client = QdrantClient(url=self.url)
            self._client.recreate_collection(
                collection_name=self.collection,
                vectors_config=qdrant_models.VectorParams(size=self.dim, distance=qdrant_models.Distance.COSINE),
            )
            self._ready = True
        except Exception:
            # Fall back to memory mode if qdrant is unavailable.
            self._ready = False

    def upsert(self, item_id: str, text: str) -> None:
        embedding = _hash_embedding(text, dim=self.dim)
        if not self._ready:
            self._fallback.upsert(item_id, text)
            return
        point = self._qdrant_models.PointStruct(
            id=item_id,
            vector=embedding,
            payload={"text": text},
        )
        self._client.upsert(collection_name=self.collection, points=[point])

    def search(self, query: str, limit: int = 5) -> list[str]:
        if not self._ready:
            return self._fallback.search(query, limit=limit)
        embedding = _hash_embedding(query, dim=self.dim)
        hits = self._client.search(collection_name=self.collection, query_vector=embedding, limit=limit)
        return [str(hit.id) for hit in hits]


def build_vector_store(backend: str, **kwargs: str) -> VectorStore:
    if backend == "qdrant":
        return QdrantVectorStore(
            collection=kwargs.get("collection", "honeycomb_memory"),
            url=kwargs.get("url", "http://localhost:6333"),
        )
    return InMemoryVectorStore()
