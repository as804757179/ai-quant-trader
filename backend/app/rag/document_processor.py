from __future__ import annotations

import re
from typing import Any


class DocumentProcessor:
    """文档分块与预处理。"""

    DEFAULT_CHUNK_SIZE = 500
    DEFAULT_OVERLAP = 50

    def chunk_by_paragraph(self, text: str, min_chunk_len: int = 80) -> list[str]:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not paragraphs:
            return [text.strip()] if text.strip() else []
        chunks: list[str] = []
        buffer = ""
        for para in paragraphs:
            if len(buffer) + len(para) + 1 <= self.DEFAULT_CHUNK_SIZE:
                buffer = f"{buffer}\n{para}".strip() if buffer else para
            else:
                if buffer and len(buffer) >= min_chunk_len:
                    chunks.append(buffer)
                buffer = para
        if buffer:
            chunks.append(buffer)
        return chunks or ([text.strip()] if text.strip() else [])

    def chunk_by_length(
        self,
        text: str,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> list[str]:
        size = chunk_size or self.DEFAULT_CHUNK_SIZE
        step = max(1, size - (overlap or self.DEFAULT_OVERLAP))
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return []
        if len(normalized) <= size:
            return [normalized]

        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(len(normalized), start + size)
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(normalized):
                break
            start += step
        return chunks

    def prepare_document(
        self,
        doc: dict[str, Any],
        *,
        content_field: str = "content",
        chunk_strategy: str = "paragraph",
    ) -> list[dict[str, Any]]:
        """
        将原始文档转为可入库的分块列表。
        每个分块包含 text + metadata（stock_code/title/publish_time 等）。
        """
        content = str(doc.get(content_field) or doc.get("text") or "").strip()
        if not content:
            return []

        title = str(doc.get("title", ""))
        if title and title not in content:
            content = f"{title}\n{content}"

        if chunk_strategy == "length":
            chunks = self.chunk_by_length(content)
        else:
            chunks = self.chunk_by_paragraph(content)

        stock_code = str(doc.get("stock_code", ""))
        publish_time = str(doc.get("publish_time", ""))
        category = str(doc.get("category", ""))
        doc_id = str(doc.get("doc_id") or doc.get("id") or f"{stock_code}_{publish_time}")

        prepared: list[dict[str, Any]] = []
        for idx, chunk in enumerate(chunks):
            prepared.append(
                {
                    "id": f"{doc_id}_chunk_{idx}",
                    "text": chunk,
                    "metadata": {
                        "stock_code": stock_code,
                        "title": title,
                        "publish_time": publish_time,
                        "category": category,
                        "doc_id": doc_id,
                        "chunk_index": idx,
                    },
                }
            )
        return prepared