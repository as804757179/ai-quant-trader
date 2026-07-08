import asyncio
import os
import tempfile
from typing import Any

import chromadb
import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")

from app.rag.document_processor import DocumentProcessor
from app.rag.engine import RAGEngine


class _FakeEmbeddingProvider:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0, 0.5] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text)), 1.0, 0.5]


@pytest.fixture
def rag_engine(tmp_path: Any) -> RAGEngine:
    client = chromadb.EphemeralClient()
    engine = RAGEngine(
        persist_dir=str(tmp_path),
        client=client,
        embedding_provider=_FakeEmbeddingProvider(),
    )
    engine.initialize_collections()
    return engine


def test_initialize_collections(rag_engine: RAGEngine) -> None:
    names = rag_engine.initialize_collections()
    assert names["research"] == "research_reports"
    assert names["announcements"] == "announcements"
    assert names["news"] == "news"
    assert rag_engine._get_collection("research").name == "research_reports"


def test_document_processor_chunking() -> None:
    processor = DocumentProcessor()
    text = "段落一内容。\n\n段落二内容更长一些，用于测试分块逻辑。"
    chunks = processor.chunk_by_paragraph(text)
    assert len(chunks) >= 1

    doc = {
        "doc_id": "ann_001",
        "stock_code": "000001",
        "title": "业绩预告",
        "publish_time": "2026-07-01",
        "content": text,
    }
    prepared = processor.prepare_document(doc)
    assert prepared
    assert prepared[0]["metadata"]["stock_code"] == "000001"


def test_index_and_retrieve_by_stock_code(rag_engine: RAGEngine) -> None:
    async def _run() -> None:
        await rag_engine.index_new_announcements(
            [
                {
                    "doc_id": "ann_a",
                    "stock_code": "000001",
                    "title": "平安银行业绩预告",
                    "publish_time": "2026-07-01",
                    "content": "净利润同比增长15%，资产质量保持稳定。",
                },
                {
                    "doc_id": "ann_b",
                    "stock_code": "600519",
                    "title": "贵州茅台分红公告",
                    "publish_time": "2026-07-02",
                    "content": "拟每10股派发现金红利200元。",
                },
            ]
        )

        result = await rag_engine.retrieve_announcements("000001", top_k=3)
        assert "平安银行" in result
        assert "贵州茅台" not in result

    asyncio.run(_run())


def test_retrieve_research_with_query(rag_engine: RAGEngine) -> None:
    async def _run() -> None:
        await rag_engine.index_new_research(
            [
                {
                    "doc_id": "rpt_001",
                    "stock_code": "000001",
                    "title": "平安银行深度研报",
                    "publish_time": "2026-06-20",
                    "content": "维持买入评级，看好零售转型与息差修复。",
                }
            ]
        )
        summary = await rag_engine.retrieve_research(
            "平安银行 研报 估值",
            top_k=2,
            stock_code="000001",
        )
        assert "买入评级" in summary or "平安银行" in summary

    asyncio.run(_run())


def test_build_rag_context(rag_engine: RAGEngine) -> None:
    async def _run() -> None:
        await rag_engine.index_new_news(
            [
                {
                    "doc_id": "news_001",
                    "stock_code": "000001",
                    "title": "平安银行获机构调研",
                    "publish_time": "2026-07-03",
                    "content": "多家机构关注其数字化转型进展。",
                }
            ]
        )
        ctx = await rag_engine.build_rag_context("000001")
        assert "research" in ctx
        assert "announcements" in ctx
        assert "news" in ctx

    asyncio.run(_run())