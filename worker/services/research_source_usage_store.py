"""Persist immutable source terms evidence and usage pre-reviews."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


CNINFO_SOURCE_SCOPE = "cninfo:hisAnnouncement/query+static.cninfo.com.cn/finalpage"
GDELT_SOURCE_SCOPE = (
    "gdelt:storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss:metadata-only"
)
FAILURE_STATUSES = {"discovery_unresolved", "fetch_failed", "validation_failed"}
USAGE_SCOPES = {
    "manual_observation",
    "automated_fetch",
    "local_storage",
    "derived_research",
    "redistribution",
}
DECISION_STATUSES = {"review_required", "rejected"}


@dataclass(frozen=True)
class SourceTermsDocument:
    provider: str
    source: str
    source_scope: str
    document_kind: str
    terms_url: str


SOURCE_TERMS_DOCUMENTS = {
    item.terms_url: item
    for item in (
        SourceTermsDocument(
            provider="cninfo",
            source="cninfo_listed_company_disclosure",
            source_scope=CNINFO_SOURCE_SCOPE,
            document_kind="other_official",
            terms_url="https://www.cninfo.com.cn/new/index.htm",
        ),
        SourceTermsDocument(
            provider="cninfo",
            source="cninfo_listed_company_disclosure",
            source_scope=CNINFO_SOURCE_SCOPE,
            document_kind="other_official",
            terms_url=(
                "https://www.cninfo.com.cn/new/commonUrl?"
                "url=disclosure%2Flist%2Fnotice"
            ),
        ),
        SourceTermsDocument(
            provider="gdelt",
            source="gdelt_article_list_rss",
            source_scope=GDELT_SOURCE_SCOPE,
            document_kind="terms_of_use",
            terms_url="https://www.gdeltproject.org/about.html",
        ),
        SourceTermsDocument(
            provider="gdelt",
            source="gdelt_article_list_rss",
            source_scope=GDELT_SOURCE_SCOPE,
            document_kind="other_official",
            terms_url=(
                "https://blog.gdeltproject.org/"
                "announcing-the-gdelt-article-list-rss-feed/"
            ),
        ),
    )
}


def get_source_terms_document(terms_url: str) -> SourceTermsDocument:
    try:
        return SOURCE_TERMS_DOCUMENTS[terms_url]
    except KeyError as exc:
        raise ValueError("条款 URL 不在 Sprint14.8-A 固定官方清单中") from exc


class ResearchSourceUsageStore:
    """Append terms observations and unapproved usage pre-reviews."""

    def __init__(self) -> None:
        database_url = os.getenv("DATABASE_URL", "")
        self._engine = create_async_engine(database_url, poolclass=NullPool)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    async def close(self) -> None:
        await self._engine.dispose()

    async def append_observed_document(
        self,
        *,
        terms_url: str,
        raw_document: bytes,
        content_type: str,
        retrieved_at: datetime,
        collector_version: str,
    ) -> dict[str, object]:
        document = get_source_terms_document(terms_url)
        if not raw_document:
            raise ValueError("官方条款响应为空")
        if retrieved_at.tzinfo is None:
            raise ValueError("条款获取时间必须包含时区")
        normalized_content_type = content_type.strip()
        if not normalized_content_type:
            raise ValueError("官方条款响应缺少 Content-Type")
        raw_hash = hashlib.sha256(raw_document).hexdigest()
        row = {
            "terms_evidence_id": uuid4(),
            "provider": document.provider,
            "source": document.source,
            "source_scope": document.source_scope,
            "document_kind": document.document_kind,
            "terms_url": document.terms_url,
            "retrieved_at": retrieved_at,
            "source_time_precision": "unresolved",
            "raw_hash": raw_hash,
            "document_bytes": len(raw_document),
            "content_type": normalized_content_type[:128],
            "status": "observed",
            "failure_reason": None,
            "collector_version": collector_version,
        }
        terms_evidence_id, inserted = await self._insert_terms_evidence(row)
        return {
            "terms_evidence_id": str(terms_evidence_id),
            "provider": document.provider,
            "source": document.source,
            "terms_url": document.terms_url,
            "status": "observed",
            "raw_hash": raw_hash,
            "document_bytes": len(raw_document),
            "inserted": inserted,
        }

    async def append_failure(
        self,
        *,
        terms_url: str,
        status: str,
        failure_reason: str,
        collector_version: str,
    ) -> dict[str, object]:
        document = get_source_terms_document(terms_url)
        if status not in FAILURE_STATUSES:
            raise ValueError("条款失败状态无效")
        normalized_reason = failure_reason.strip()
        if not normalized_reason:
            raise ValueError("条款失败记录必须包含原因")
        row = {
            "terms_evidence_id": uuid4(),
            "provider": document.provider,
            "source": document.source,
            "source_scope": document.source_scope,
            "document_kind": document.document_kind,
            "terms_url": document.terms_url,
            "retrieved_at": None,
            "source_time_precision": "unresolved",
            "raw_hash": None,
            "document_bytes": None,
            "content_type": None,
            "status": status,
            "failure_reason": normalized_reason[:2000],
            "collector_version": collector_version,
        }
        terms_evidence_id, inserted = await self._insert_terms_evidence(row)
        return {
            "terms_evidence_id": str(terms_evidence_id),
            "provider": document.provider,
            "source": document.source,
            "terms_url": document.terms_url,
            "status": status,
            "failure_reason": normalized_reason[:2000],
            "inserted": inserted,
        }

    async def append_usage_review(
        self,
        *,
        terms_evidence_id: UUID,
        usage_scope: str,
        decision_status: str,
        reason: str,
        reviewer_label: str,
        policy_version: str,
    ) -> dict[str, object]:
        if usage_scope not in USAGE_SCOPES:
            raise ValueError("使用范围不在固定清单中")
        if decision_status not in DECISION_STATUSES:
            raise ValueError("预审结论只允许 review_required 或 rejected")
        normalized_reason = reason.strip()
        normalized_reviewer = reviewer_label.strip()
        normalized_policy = policy_version.strip()
        if not normalized_reason or not normalized_reviewer or not normalized_policy:
            raise ValueError("预审原因、记录者标签和策略版本不能为空")
        review_id = uuid4()
        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO market.research_source_usage_reviews (
                        review_id, terms_evidence_id, usage_scope, decision_status,
                        reason, reviewer_label, identity_assurance, policy_version
                    ) VALUES (
                        :review_id, :terms_evidence_id, :usage_scope, :decision_status,
                        :reason, :reviewer_label, 'unverified', :policy_version
                    )
                    """
                ),
                {
                    "review_id": review_id,
                    "terms_evidence_id": terms_evidence_id,
                    "usage_scope": usage_scope,
                    "decision_status": decision_status,
                    "reason": normalized_reason,
                    "reviewer_label": normalized_reviewer,
                    "policy_version": normalized_policy,
                },
            )
            await session.commit()
        return {
            "review_id": str(review_id),
            "terms_evidence_id": str(terms_evidence_id),
            "usage_scope": usage_scope,
            "decision_status": decision_status,
            "identity_assurance": "unverified",
            "policy_version": normalized_policy,
        }

    async def _insert_terms_evidence(
        self, row: dict[str, object]
    ) -> tuple[UUID, bool]:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    INSERT INTO market.research_source_terms_evidence (
                        terms_evidence_id, provider, source, source_scope,
                        document_kind, terms_url, retrieved_at,
                        source_time_precision, raw_hash, document_bytes,
                        content_type, status, failure_reason, collector_version
                    ) VALUES (
                        :terms_evidence_id, :provider, :source, :source_scope,
                        :document_kind, :terms_url, :retrieved_at,
                        :source_time_precision, :raw_hash, :document_bytes,
                        :content_type, :status, :failure_reason, :collector_version
                    )
                    ON CONFLICT (provider, source, source_scope, terms_url, raw_hash)
                    DO NOTHING
                    RETURNING terms_evidence_id
                    """
                ),
                row,
            )
            terms_evidence_id = result.scalar_one_or_none()
            inserted = terms_evidence_id is not None
            if terms_evidence_id is None:
                existing = await session.execute(
                    text(
                        """
                        SELECT terms_evidence_id
                        FROM market.research_source_terms_evidence
                        WHERE provider = :provider
                          AND source = :source
                          AND source_scope = :source_scope
                          AND terms_url = :terms_url
                          AND raw_hash = :raw_hash
                        """
                    ),
                    row,
                )
                terms_evidence_id = existing.scalar_one()
            await session.commit()
        return terms_evidence_id, inserted
