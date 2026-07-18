"""Create hash-matched local snapshots for fixed financial report evidence."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


FIXED_FINANCIAL_EVIDENCE_IDS = {
    UUID("cef779d8-96d7-4a01-8ae3-2b9a023447e0"),
    UUID("522d97a3-ff33-4001-81da-6575cd4ad8e3"),
}
COLLECTOR_VERSION = "sprint14.9-financial-snapshot-v1"


def default_snapshot_root() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("缺少 LOCALAPPDATA，无法确定受管财报证据目录")
    return (
        Path(local_app_data)
        / "AIQuantTrader"
        / "evidence"
        / "financial_reports"
        / "cninfo"
    )


def validate_pdf_response(
    candidate: dict[str, Any], raw_document: bytes, content_type: str
) -> tuple[str, int]:
    if not raw_document or not raw_document.startswith(b"%PDF-"):
        raise ValueError("原文响应不是可验证的 PDF")
    if "pdf" not in content_type.lower():
        raise ValueError("原文响应 Content-Type 不是 PDF")
    observed_hash = hashlib.sha256(raw_document).hexdigest()
    observed_bytes = len(raw_document)
    if observed_hash != candidate["expected_raw_hash"]:
        raise RuntimeError("原文 SHA-256 与既有证据不一致")
    if observed_bytes != candidate["expected_bytes"]:
        raise RuntimeError("原文字节数与既有证据不一致")
    return observed_hash, observed_bytes


def write_snapshot_atomically(
    snapshot_root: Path, storage_key: str, raw_document: bytes
) -> Path:
    if Path(storage_key).name != storage_key or not storage_key.lower().endswith(".pdf"):
        raise ValueError("财报快照 storage_key 无效")
    snapshot_root.mkdir(parents=True, exist_ok=True)
    target = snapshot_root / storage_key
    if target.exists():
        if target.read_bytes() != raw_document:
            raise RuntimeError("目标快照已存在但字节不一致")
        return target
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=snapshot_root, prefix=".snapshot-", suffix=".tmp", delete=False
        ) as temporary:
            temporary.write(raw_document)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.replace(target)
        return target
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


class FinancialReportSnapshotStore:
    """Persist fixed-scope snapshot attempts without changing source evidence."""

    def __init__(self, snapshot_root: Path | None = None) -> None:
        self.snapshot_root = snapshot_root or default_snapshot_root()
        database_url = os.getenv("DATABASE_URL", "")
        self._engine = create_async_engine(database_url, poolclass=NullPool)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    async def close(self) -> None:
        await self._engine.dispose()

    async def get_candidate(self, evidence_id: UUID) -> dict[str, Any]:
        if evidence_id not in FIXED_FINANCIAL_EVIDENCE_IDS:
            raise ValueError("Evidence ID 不在 Sprint14.9 固定范围中")
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT evidence.evidence_id, evidence.stock_code,
                           evidence.source_document_id, evidence.document_url,
                           evidence.raw_hash AS expected_raw_hash,
                           evidence.document_bytes AS expected_bytes,
                           usage_review.review_id AS source_usage_review_id,
                           existing.snapshot_id AS existing_snapshot_id,
                           existing.storage_key AS existing_storage_key
                    FROM market.research_evidence AS evidence
                    JOIN LATERAL (
                        SELECT review.review_id
                        FROM market.research_source_usage_reviews AS review
                        JOIN market.research_source_terms_evidence AS terms
                          ON terms.terms_evidence_id = review.terms_evidence_id
                        WHERE terms.provider = evidence.provider
                          AND terms.source = evidence.source
                          AND review.usage_scope = 'local_storage'
                          AND review.decision_status = 'review_required'
                          AND review.identity_assurance = 'unverified'
                        ORDER BY review.reviewed_at DESC, review.review_id DESC
                        LIMIT 1
                    ) AS usage_review ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT snapshot.snapshot_id, snapshot.storage_key
                        FROM market.research_financial_report_snapshots AS snapshot
                        WHERE snapshot.evidence_id = evidence.evidence_id
                          AND snapshot.status = 'observed'
                        ORDER BY snapshot.created_at DESC, snapshot.snapshot_id DESC
                        LIMIT 1
                    ) AS existing ON TRUE
                    WHERE evidence.evidence_id = :evidence_id
                      AND evidence.evidence_type = 'financial_report'
                      AND evidence.quality_status = 'observed'
                      AND evidence.provider = 'cninfo'
                      AND evidence.source = 'cninfo_listed_company_disclosure'
                      AND evidence.usage_status = 'review_required'
                    """
                ),
                {"evidence_id": evidence_id},
            )
            row = result.mappings().one_or_none()
        if row is None:
            raise ValueError("固定财报证据不存在或来源治理状态不符合要求")
        candidate = dict(row)
        expected_url = (
            "https://static.cninfo.com.cn/finalpage/"
        )
        if not str(candidate["document_url"]).startswith(expected_url):
            raise ValueError("财报原文 URL 不属于固定 CNINFO finalpage 范围")
        if not str(candidate["document_url"]).upper().endswith(
            f"/{candidate['source_document_id']}.PDF"
        ):
            raise ValueError("财报原文 URL 未与 CNINFO 文档 ID 绑定")
        return candidate

    def validate_existing_snapshot(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        snapshot_id = candidate.get("existing_snapshot_id")
        storage_key = candidate.get("existing_storage_key")
        if snapshot_id is None or storage_key is None:
            return None
        path = self.snapshot_root / str(storage_key)
        if not path.is_file():
            raise RuntimeError("数据库快照记录存在，但本地 PDF 文件缺失")
        raw_document = path.read_bytes()
        validate_pdf_response(candidate, raw_document, "application/pdf")
        return {
            "snapshot_id": str(snapshot_id),
            "evidence_id": str(candidate["evidence_id"]),
            "stock_code": candidate["stock_code"],
            "status": "observed",
            "storage_key": str(storage_key),
            "inserted": False,
        }

    async def persist_observed(
        self,
        candidate: dict[str, Any],
        raw_document: bytes,
        content_type: str,
        fetched_at: datetime,
    ) -> dict[str, Any]:
        observed_hash, observed_bytes = validate_pdf_response(
            candidate, raw_document, content_type
        )
        storage_key = f"{candidate['source_document_id']}_{observed_hash}.pdf"
        target_existed = (self.snapshot_root / storage_key).exists()
        target = write_snapshot_atomically(self.snapshot_root, storage_key, raw_document)
        stored_at = datetime.now(timezone.utc)
        row = {
            "snapshot_id": uuid4(),
            "evidence_id": candidate["evidence_id"],
            "source_usage_review_id": candidate["source_usage_review_id"],
            "expected_raw_hash": candidate["expected_raw_hash"],
            "observed_raw_hash": observed_hash,
            "expected_bytes": candidate["expected_bytes"],
            "observed_bytes": observed_bytes,
            "content_type": "application/pdf",
            "storage_key": storage_key,
            "status": "observed",
            "failure_reason": None,
            "fetched_at": fetched_at,
            "received_at": stored_at,
            "stored_at": stored_at,
            "collector_version": COLLECTOR_VERSION,
        }
        try:
            snapshot_id, inserted = await self._insert_snapshot(row)
        except Exception:
            if not target_existed and target.exists():
                target.unlink()
            raise
        return {
            "snapshot_id": str(snapshot_id),
            "evidence_id": str(candidate["evidence_id"]),
            "stock_code": candidate["stock_code"],
            "status": "observed",
            "raw_hash": observed_hash,
            "document_bytes": observed_bytes,
            "storage_key": storage_key,
            "inserted": inserted,
        }

    async def persist_failure(
        self,
        candidate: dict[str, Any],
        *,
        status: str,
        failure_reason: str,
        fetched_at: datetime | None = None,
        observed_raw_hash: str | None = None,
        observed_bytes: int | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        if status not in {
            "hash_mismatch",
            "fetch_failed",
            "validation_failed",
            "write_failed",
        }:
            raise ValueError("财报快照失败状态无效")
        row = {
            "snapshot_id": uuid4(),
            "evidence_id": candidate["evidence_id"],
            "source_usage_review_id": candidate["source_usage_review_id"],
            "expected_raw_hash": candidate["expected_raw_hash"],
            "observed_raw_hash": observed_raw_hash,
            "expected_bytes": candidate["expected_bytes"],
            "observed_bytes": observed_bytes,
            "content_type": content_type[:128] if content_type else None,
            "storage_key": None,
            "status": status,
            "failure_reason": failure_reason.strip()[:2000],
            "fetched_at": fetched_at,
            "received_at": datetime.now(timezone.utc),
            "stored_at": None,
            "collector_version": COLLECTOR_VERSION,
        }
        snapshot_id, _ = await self._insert_snapshot(row)
        return {
            "snapshot_id": str(snapshot_id),
            "evidence_id": str(candidate["evidence_id"]),
            "stock_code": candidate["stock_code"],
            "status": status,
            "failure_reason": row["failure_reason"],
            "inserted": True,
        }

    async def _insert_snapshot(
        self, row: dict[str, Any]
    ) -> tuple[UUID, bool]:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    INSERT INTO market.research_financial_report_snapshots (
                        snapshot_id, evidence_id, source_usage_review_id,
                        expected_raw_hash, observed_raw_hash,
                        expected_bytes, observed_bytes, content_type,
                        acquisition_method, storage_key, status, failure_reason,
                        fetched_at, received_at, stored_at, collector_version
                    ) VALUES (
                        :snapshot_id, :evidence_id, :source_usage_review_id,
                        :expected_raw_hash, :observed_raw_hash,
                        :expected_bytes, :observed_bytes, :content_type,
                        'explicit_refetch', :storage_key, :status, :failure_reason,
                        :fetched_at, :received_at, :stored_at, :collector_version
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING snapshot_id
                    """
                ),
                row,
            )
            snapshot_id = result.scalar_one_or_none()
            inserted = snapshot_id is not None
            if snapshot_id is None and row["status"] == "observed":
                existing = await session.execute(
                    text(
                        """
                        SELECT snapshot_id
                        FROM market.research_financial_report_snapshots
                        WHERE evidence_id = :evidence_id
                          AND expected_raw_hash = :expected_raw_hash
                          AND status = 'observed'
                        """
                    ),
                    row,
                )
                snapshot_id = existing.scalar_one()
            if snapshot_id is None:
                raise RuntimeError("财报快照失败审计写入被数据库拒绝")
            await session.commit()
        return snapshot_id, inserted
