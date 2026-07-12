"""公告轻量索引：从 DB 取最新公告写入 Chroma。"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text

from app.db import get_db
from app.rag.engine import RAGEngine

logger = structlog.get_logger(__name__)


async def index_new_announcements(limit: int = 50) -> dict[str, Any]:
    """扫描 fundamental.announcements 最近记录，写入 announcements collection。"""
    rows: list[dict[str, Any]] = []
    try:
        async with get_db() as db:
            result = await db.execute(
                text(
                    """
                    SELECT stock_code, title, publish_time, content_url, category
                    FROM fundamental.announcements
                    ORDER BY publish_time DESC NULLS LAST
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
            rows = [dict(r) for r in result.mappings().all()]
    except Exception as exc:
        logger.warning("announcements_query_failed", error=str(exc))
        return {
            "status": "degraded",
            "indexed": 0,
            "error": str(exc),
            "message": "announcements 表不可用或查询失败",
        }

    if not rows:
        return {"status": "ok", "indexed": 0, "message": "no announcements"}

    engine = RAGEngine()
    try:
        engine.initialize_collections()
        coll = engine._get_collection("announcements")
        docs: list[str] = []
        ids: list[str] = []
        metas: list[dict[str, Any]] = []
        for i, row in enumerate(rows):
            title = str(row.get("title") or "").strip()
            code = str(row.get("stock_code") or "")
            if not title:
                continue
            body = f"{code} {title}"
            if row.get("category"):
                body += f" [{row['category']}]"
            doc_id = f"ann:{code}:{abs(hash(title)) % 10_000_000}:{i}"
            docs.append(body)
            ids.append(doc_id)
            metas.append(
                {
                    "stock_code": code,
                    "title": title[:200],
                    "url": str(row.get("content_url") or ""),
                }
            )
        if not docs:
            return {"status": "ok", "indexed": 0}

        provider = engine.embedding_provider
        try:
            embeddings = provider.embed_documents(docs)
        except Exception as emb_exc:
            logger.warning("embed_failed", error=str(emb_exc))
            embeddings = []

        if embeddings and len(embeddings) == len(docs):
            coll.upsert(
                ids=ids,
                documents=docs,
                embeddings=embeddings,
                metadatas=metas,
            )
        else:
            try:
                coll.upsert(ids=ids, documents=docs, metadatas=metas)
            except Exception as exc:
                logger.warning("chroma_upsert_failed", error=str(exc))
                return {"status": "degraded", "indexed": 0, "error": str(exc)}

        logger.info("announcements_indexed", count=len(docs))
        return {"status": "ok", "indexed": len(docs)}
    except Exception as exc:
        logger.warning("index_announcements_failed", error=str(exc))
        return {"status": "degraded", "indexed": 0, "error": str(exc)}
