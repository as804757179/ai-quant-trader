from __future__ import annotations

from typing import Protocol

import structlog

logger = structlog.get_logger(__name__)


class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class ChromaEmbeddingProvider:
    """基于 ChromaDB 默认 ONNX 模型的 embedding 封装。"""

    def __init__(self) -> None:
        from chromadb.utils import embedding_functions

        self._ef = embedding_functions.DefaultEmbeddingFunction()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._ef(texts)

    def embed_query(self, text: str) -> list[float]:
        vectors = self._ef([text])
        return vectors[0] if vectors else []


def get_embedding_provider() -> EmbeddingProvider:
    logger.debug("embedding_provider_init", provider="chroma_default")
    return ChromaEmbeddingProvider()