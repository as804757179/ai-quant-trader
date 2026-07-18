"""Extract immutable page evidence and conservative financial-report locations."""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from services.financial_report_snapshot_store import (
    FIXED_FINANCIAL_EVIDENCE_IDS,
    default_snapshot_root,
)


PARSER_NAME = "pypdf"
PARSER_VERSION = "3.17.4"
NORMALIZATION_VERSION = "financial-page-text-nfkc-v1"
LOCATOR_VERSION = "financial-metadata-locator-v1"
MAX_CANDIDATES_PER_FIELD = 100

FIELD_PATTERNS = {
    "report_period_end": re.compile(
        r"(20\d{2})\s*[年./-]\s*(0?[1-9]|1[0-2])\s*[月./-]\s*(0?[1-9]|[12]\d|3[01])\s*日?"
    ),
    "statement_currency_unit": re.compile(
        r"(?:单位|币种)\s*[:：]\s*(人民币)?\s*(元|千元|万元|百万元|亿元)"
    ),
    "audit_opinion_section": re.compile(r"审计意见"),
    "statement_scope_heading": re.compile(
        r"(合并|母公司)\s*(资产负债表|利润表|现金流量表|所有者权益变动表)"
    ),
}


def normalize_page_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in normalized.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def extract_pdf_pages(path: Path) -> tuple[list[dict[str, Any]], bool]:
    reader = PdfReader(str(path))
    pages: list[dict[str, Any]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            page_text = normalize_page_text(page.extract_text() or "")
            if page_text:
                pages.append(
                    {
                        "page_evidence_id": uuid4(),
                        "page_number": page_number,
                        "extraction_status": "text_observed",
                        "text": page_text,
                        "text_hash": hashlib.sha256(page_text.encode("utf-8")).hexdigest(),
                        "character_count": len(page_text),
                        "failure_reason": None,
                    }
                )
            else:
                pages.append(
                    {
                        "page_evidence_id": uuid4(),
                        "page_number": page_number,
                        "extraction_status": "empty",
                        "text": "",
                        "text_hash": None,
                        "character_count": 0,
                        "failure_reason": "pypdf 未提取到可验证文本",
                    }
                )
        except Exception as exc:
            pages.append(
                {
                    "page_evidence_id": uuid4(),
                    "page_number": page_number,
                    "extraction_status": "failed",
                    "text": "",
                    "text_hash": None,
                    "character_count": None,
                    "failure_reason": f"页面文本提取失败：{type(exc).__name__}: {exc}"[:2000],
                }
            )
    return pages, bool(getattr(reader, "is_encrypted", False))


def _normalized_value(field_name: str, match: re.Match[str]) -> tuple[str, str]:
    if field_name == "report_period_end":
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}", "unresolved"
    if field_name == "statement_currency_unit":
        prefix = match.group(1) or ""
        return f"{prefix}{match.group(2)}", "unresolved"
    if field_name == "statement_scope_heading":
        scope = "consolidated" if match.group(1) == "合并" else "parent_company"
        return f"{scope}:{match.group(2)}", scope
    return "audit_opinion_section", "unresolved"


def locate_metadata(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = []
    for field_name, pattern in FIELD_PATTERNS.items():
        candidates: list[dict[str, Any]] = []
        truncated = False
        for page in pages:
            if page["extraction_status"] != "text_observed":
                continue
            for match in pattern.finditer(page["text"]):
                if len(candidates) >= MAX_CANDIDATES_PER_FIELD:
                    truncated = True
                    break
                normalized_value, statement_scope = _normalized_value(field_name, match)
                anchor = page["text"][max(0, match.start() - 80) : match.end() + 80]
                candidates.append(
                    {
                        "location_id": uuid4(),
                        "page_evidence_id": page["page_evidence_id"],
                        "field_name": field_name,
                        "raw_value": match.group(0)[:500],
                        "normalized_value": normalized_value[:128],
                        "match_start": match.start(),
                        "match_end": match.end(),
                        "anchor_hash": hashlib.sha256(anchor.encode("utf-8")).hexdigest(),
                        "statement_scope": statement_scope,
                    }
                )
            if truncated:
                break
        if not candidates:
            locations.append(
                {
                    "location_id": uuid4(),
                    "page_evidence_id": None,
                    "field_name": field_name,
                    "raw_value": None,
                    "normalized_value": None,
                    "match_start": None,
                    "match_end": None,
                    "anchor_hash": None,
                    "statement_scope": "unresolved",
                    "status": "unresolved",
                    "reason": "未在 pypdf 可提取文本中定位到候选值",
                }
            )
            continue
        unique = len(candidates) == 1 and not truncated
        for candidate in candidates:
            candidate["status"] = "located" if unique else "ambiguous"
            candidate["reason"] = None if unique else (
                "候选超过 100 个，已按页码和字符偏移截断" if truncated else "存在多个候选，未推断唯一值"
            )
            locations.append(candidate)
    return locations


class FinancialReportPageLocationStore:
    def __init__(self, snapshot_root: Path | None = None) -> None:
        self.snapshot_root = snapshot_root or default_snapshot_root()
        self._engine = create_async_engine(os.getenv("DATABASE_URL", ""), poolclass=NullPool)
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
                    SELECT snapshot.snapshot_id, snapshot.evidence_id, snapshot.storage_key,
                           snapshot.observed_raw_hash, evidence.stock_code,
                           usage_review.review_id AS source_usage_review_id,
                           existing.parse_run_id AS existing_parse_run_id
                    FROM market.research_financial_report_snapshots AS snapshot
                    JOIN market.research_evidence AS evidence
                      ON evidence.evidence_id = snapshot.evidence_id
                    JOIN LATERAL (
                        SELECT review.review_id
                        FROM market.research_source_usage_reviews AS review
                        JOIN market.research_source_terms_evidence AS terms
                          ON terms.terms_evidence_id = review.terms_evidence_id
                        WHERE terms.provider = 'cninfo'
                          AND terms.source = 'cninfo_listed_company_disclosure'
                          AND review.usage_scope = 'derived_research'
                          AND review.decision_status = 'review_required'
                          AND review.identity_assurance = 'unverified'
                        ORDER BY review.reviewed_at DESC, review.review_id DESC
                        LIMIT 1
                    ) AS usage_review ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT run.parse_run_id
                        FROM market.research_financial_report_parse_runs AS run
                        WHERE run.snapshot_id = snapshot.snapshot_id
                          AND run.parser_name = 'pypdf'
                          AND run.parser_version = '3.17.4'
                          AND run.normalization_version = :normalization_version
                          AND run.status IN ('success', 'partial')
                        ORDER BY run.completed_at DESC, run.parse_run_id DESC
                        LIMIT 1
                    ) AS existing ON TRUE
                    WHERE snapshot.evidence_id = :evidence_id
                      AND snapshot.status = 'observed'
                    ORDER BY snapshot.created_at DESC, snapshot.snapshot_id DESC
                    LIMIT 1
                    """
                ),
                {"evidence_id": evidence_id, "normalization_version": NORMALIZATION_VERSION},
            )
            row = result.mappings().one_or_none()
        if row is None:
            raise ValueError("固定财报证据缺少已验真的本地快照或派生研究审查")
        candidate = dict(row)
        path = self.snapshot_root / str(candidate["storage_key"])
        if not path.is_file():
            raise RuntimeError("已验真财报快照文件缺失")
        if hashlib.sha256(path.read_bytes()).hexdigest() != candidate["observed_raw_hash"]:
            raise RuntimeError("本地财报快照 Hash 与数据库不一致")
        candidate["path"] = path
        return candidate

    async def persist(
        self,
        candidate: dict[str, Any],
        pages: list[dict[str, Any]],
        locations: list[dict[str, Any]],
        started_at: datetime,
        encrypted: bool,
    ) -> dict[str, Any]:
        if candidate.get("existing_parse_run_id") is not None:
            return {
                "parse_run_id": str(candidate["existing_parse_run_id"]),
                "status": "existing",
                "inserted": False,
            }
        page_count = len(pages)
        text_page_count = sum(page["extraction_status"] == "text_observed" for page in pages)
        if page_count == 0 or text_page_count == 0:
            raise RuntimeError("pypdf 未产生可写入的页级文本证据")
        status = "success" if text_page_count == page_count else "partial"
        failure_reason = None if status == "success" else (
            f"{page_count - text_page_count} 页未提取到文本" + ("；PDF 标记为加密" if encrypted else "")
        )
        parse_run_id = uuid4()
        completed_at = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO market.research_financial_report_parse_runs (
                            parse_run_id, snapshot_id, source_usage_review_id,
                            parser_name, parser_version, normalization_version,
                            status, page_count, text_page_count, failure_reason,
                            started_at, completed_at
                        ) VALUES (
                            :parse_run_id, :snapshot_id, :source_usage_review_id,
                            :parser_name, :parser_version, :normalization_version,
                            :status, :page_count, :text_page_count, :failure_reason,
                            :started_at, :completed_at
                        )
                        """
                    ),
                    {
                        "parse_run_id": parse_run_id,
                        "snapshot_id": candidate["snapshot_id"],
                        "source_usage_review_id": candidate["source_usage_review_id"],
                        "parser_name": PARSER_NAME,
                        "parser_version": PARSER_VERSION,
                        "normalization_version": NORMALIZATION_VERSION,
                        "status": status,
                        "page_count": page_count,
                        "text_page_count": text_page_count,
                        "failure_reason": failure_reason,
                        "started_at": started_at,
                        "completed_at": completed_at,
                    },
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO market.research_financial_report_page_evidence (
                            page_evidence_id, parse_run_id, page_number,
                            extraction_status, text_hash, character_count, failure_reason
                        ) VALUES (
                            :page_evidence_id, :parse_run_id, :page_number,
                            :extraction_status, :text_hash, :character_count, :failure_reason
                        )
                        """
                    ),
                    [{**page, "parse_run_id": parse_run_id} for page in pages],
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO market.research_financial_metadata_locations (
                            location_id, parse_run_id, page_evidence_id, field_name,
                            raw_value, normalized_value, match_start, match_end,
                            anchor_hash, statement_scope, status, reason, locator_version
                        ) VALUES (
                            :location_id, :parse_run_id, :page_evidence_id, :field_name,
                            :raw_value, :normalized_value, :match_start, :match_end,
                            :anchor_hash, :statement_scope, :status, :reason, :locator_version
                        )
                        """
                    ),
                    [
                        {**location, "parse_run_id": parse_run_id, "locator_version": LOCATOR_VERSION}
                        for location in locations
                    ],
                )
        return {
            "parse_run_id": str(parse_run_id),
            "status": status,
            "page_count": page_count,
            "text_page_count": text_page_count,
            "location_count": len(locations),
            "inserted": True,
        }
