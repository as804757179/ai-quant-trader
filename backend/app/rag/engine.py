from __future__ import annotations

import asyncio
from typing import Any

import chromadb
import structlog

from app.core.config import settings
from app.rag.document_processor import DocumentProcessor
from app.rag.embeddings import EmbeddingProvider, get_embedding_provider

logger = structlog.get_logger(__name__)

COLLECTION_RESEARCH = "research_reports"
COLLECTION_ANNOUNCEMENTS = "announcements"
COLLECTION_NEWS = "news"


class RAGEngine:
    """ChromaDB 向量检索引擎。"""

    def __init__(
        self,
        persist_dir: str | None = None,
        client: chromadb.ClientAPI | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        processor: DocumentProcessor | None = None,
    ) -> None:
        self.persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR
        self._client = client
        self._embedding_provider = embedding_provider
        self.processor = processor or DocumentProcessor()
        self._collections: dict[str, chromadb.Collection] = {}

    @property
    def client(self) -> chromadb.ClientAPI:
        if self._client is None:
            self._client = chromadb.PersistentClient(path=self.persist_dir)
        return self._client

    @property
    def embedding_provider(self) -> EmbeddingProvider:
        if self._embedding_provider is None:
            self._embedding_provider = get_embedding_provider()
        return self._embedding_provider

    def initialize_collections(self) -> dict[str, str]:
        """初始化 3 个 collection，返回名称映射。"""
        names = {
            "research": settings.CHROMA_COLLECTION_REPORTS,
            "announcements": settings.CHROMA_COLLECTION_ANNOUNCEMENTS,
            "news": settings.CHROMA_COLLECTION_NEWS,
        }
        for key, name in names.items():
            self._collections[key] = self.client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("rag_collection_ready", collection=name, key=key)
        return names

    def _get_collection(self, key: str) -> chromadb.Collection:
        if key not in self._collections:
            self.initialize_collections()
        return self._collections[key]

    async def retrieve_research(
        self,
        query: str,
        top_k: int = 5,
        *,
        stock_code: str | None = None,
    ) -> str:
        return await self._retrieve(
            collection_key="research",
            query=query,
            top_k=top_k,
            stock_code=stock_code,
        )

    async def retrieve_announcements(
        self, stock_code: str, top_k: int = 5
    ) -> str:
        query = f"{stock_code} 公司公告 重大事项"
        return await self._retrieve(
            collection_key="announcements",
            query=query,
            top_k=top_k,
            stock_code=stock_code,
        )

    async def retrieve_news(self, stock_code: str, top_k: int = 5) -> str:
        query = f"{stock_code} 相关新闻 市场动态"
        return await self._retrieve(
            collection_key="news",
            query=query,
            top_k=top_k,
            stock_code=stock_code,
        )

    async def build_rag_context(self, stock_code: str) -> dict[str, str]:
        """构建可写入 context['rag_context'] 的检索摘要。"""
        logger.info("rag_query", stock_code=stock_code, scope="full_context")
        research, announcements, news = await asyncio.gather(
            self.retrieve_research(stock_code, top_k=3, stock_code=stock_code),
            self.retrieve_announcements(stock_code, top_k=5),
            self.retrieve_news(stock_code, top_k=5),
        )
        return {
            "research": research or "暂无相关研报",
            "announcements": announcements or "暂无近期重大公告",
            "news": news or "暂无相关新闻",
        }

    async def _retrieve(
        self,
        collection_key: str,
        query: str,
        top_k: int,
        stock_code: str | None = None,
    ) -> str:
        logger.info(
            "rag_query",
            collection=collection_key,
            query=query[:120],
            stock_code=stock_code,
            top_k=top_k,
        )
        hits = await asyncio.to_thread(
            self._query_collection,
            collection_key,
            query,
            top_k,
            stock_code,
        )
        if not hits:
            logger.info(
                "rag_retrieved",
                collection=collection_key,
                stock_code=stock_code,
                hit_count=0,
            )
            return ""

        summary = self._format_hits(hits)
        logger.info(
            "rag_retrieved",
            collection=collection_key,
            stock_code=stock_code,
            hit_count=len(hits),
        )
        return summary

    def _query_collection(
        self,
        collection_key: str,
        query: str,
        top_k: int,
        stock_code: str | None,
    ) -> list[dict[str, Any]]:
        collection = self._get_collection(collection_key)
        if collection.count() == 0:
            return []

        query_kwargs: dict[str, Any] = {
            "query_embeddings": [self.embedding_provider.embed_query(query)],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if stock_code:
            query_kwargs["where"] = {"stock_code": stock_code}

        try:
            result = collection.query(**query_kwargs)
        except Exception as exc:
            logger.warning(
                "rag_query_failed",
                collection=collection_key,
                stock_code=stock_code,
                error=str(exc),
            )
            return []

        documents = result.get("documents") or [[]]
        metadatas = result.get("metadatas") or [[]]
        distances = result.get("distances") or [[]]

        hits: list[dict[str, Any]] = []
        for doc, meta, distance in zip(
            documents[0], metadatas[0], distances[0], strict=False
        ):
            if not doc:
                continue
            hits.append(
                {
                    "text": doc,
                    "metadata": meta or {},
                    "distance": distance,
                }
            )
        return hits

    @staticmethod
    def _format_hits(hits: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for hit in hits:
            meta = hit.get("metadata") or {}
            title = meta.get("title") or "无标题"
            publish_time = meta.get("publish_time") or "未知日期"
            text = str(hit.get("text", "")).strip()
            if len(text) > 300:
                text = text[:300] + "..."
            lines.append(f"[{publish_time}] {title}\n{text}")
        return "\n\n".join(lines)

    def _upsert_chunks(
        self, collection_key: str, chunks: list[dict[str, Any]]
    ) -> int:
        if not chunks:
            return 0
        collection = self._get_collection(collection_key)
        ids = [chunk["id"] for chunk in chunks]
        documents = [chunk["text"] for chunk in chunks]
        metadatas = [chunk["metadata"] for chunk in chunks]
        embeddings = self.embedding_provider.embed_documents(documents)
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        return len(chunks)

    async def index_documents(
        self,
        collection_key: str,
        documents: list[dict[str, Any]],
        *,
        chunk_strategy: str = "paragraph",
    ) -> int:
        """通用文档入库接口。"""
        all_chunks: list[dict[str, Any]] = []
        for doc in documents:
            all_chunks.extend(
                self.processor.prepare_document(doc, chunk_strategy=chunk_strategy)
            )
        count = await asyncio.to_thread(
            self._upsert_chunks, collection_key, all_chunks
        )
        logger.info(
            "rag_indexed",
            collection=collection_key,
            document_count=len(documents),
            chunk_count=count,
        )
        return count

    async def index_new_announcements(self, documents: list[dict[str, Any]]) -> int:
        return await self.index_documents("announcements", documents)

    async def index_new_research(self, documents: list[dict[str, Any]]) -> int:
        return await self.index_documents("research", documents)

    async def index_new_news(self, documents: list[dict[str, Any]]) -> int:
        return await self.index_documents("news", documents)