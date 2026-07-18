"""Persist read-only research evidence with immutable provenance."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


CNINFO_PROVIDER = "cninfo"
CNINFO_SOURCE = "cninfo_listed_company_disclosure"
CNINFO_QUERY_ENDPOINT = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_DOCUMENT_BASE_URL = "https://static.cninfo.com.cn/"
CNINFO_ANNUAL_REPORT_CATEGORY = "category_ndbg_szsh"
GDELT_PROVIDER = "gdelt"
GDELT_SOURCE = "gdelt_article_list_rss"
GDELT_GAL_RSS_ENDPOINT = "https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss"
GDELT_RSS_WINDOW_MINUTES = 15
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ANNUAL_REPORT_TITLE = re.compile(r"^(?:.+)?(?P<year>\d{4})年年度报告$")


def _parse_iso(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_date(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _invalid_document_id(item: dict[str, Any]) -> str:
    payload = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
    return f"invalid-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]}"


def _evidence_label(evidence_type: str) -> str:
    return {
        "announcement": "公告",
        "financial_report": "年报",
        "news": "新闻",
    }.get(evidence_type, "研究")


class ResearchEvidenceStore:
    """Write observed research evidence without changing readiness or release gates."""

    def __init__(self) -> None:
        database_url = os.getenv("DATABASE_URL", "")
        self._engine = create_async_engine(database_url, poolclass=NullPool)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    async def close(self) -> None:
        await self._engine.dispose()

    async def persist_batch(
        self,
        requested_codes: list[str],
        items: list[dict[str, Any]],
        metadata: dict[str, Any],
        started_at: datetime,
    ) -> dict[str, Any]:
        return await self._persist_batch(
            requested_codes,
            items,
            metadata,
            started_at,
            evidence_type="announcement",
        )

    async def persist_financial_report_batch(
        self,
        requested_codes: list[str],
        items: list[dict[str, Any]],
        metadata: dict[str, Any],
        started_at: datetime,
    ) -> dict[str, Any]:
        return await self._persist_batch(
            requested_codes,
            items,
            metadata,
            started_at,
            evidence_type="financial_report",
        )

    async def persist_news_batch(
        self,
        requested_codes: list[str],
        items: list[dict[str, Any]],
        metadata: dict[str, Any],
        started_at: datetime,
    ) -> dict[str, Any]:
        return await self._persist_batch(
            requested_codes,
            items,
            metadata,
            started_at,
            evidence_type="news",
        )

    async def _persist_batch(
        self,
        requested_codes: list[str],
        items: list[dict[str, Any]],
        metadata: dict[str, Any],
        started_at: datetime,
        *,
        evidence_type: str,
    ) -> dict[str, Any]:
        requested = list(dict.fromkeys(str(code).strip().upper() for code in requested_codes if code))
        batch_id = uuid4()
        received_at = datetime.now(timezone.utc)
        provider = str(metadata.get("provider") or "")
        source = str(metadata.get("source") or "")
        endpoint = str(metadata.get("fetch_endpoint") or "")
        fallback_used = bool(metadata.get("fallback_used"))
        usage_status = str(metadata.get("usage_status") or "review_required")
        supplied_status = str(metadata.get("status") or "fetch_failed")
        failure_reason = metadata.get("failure_reason")
        fetched_at = _parse_iso(metadata.get("fetched_at"))
        collector_version = str(metadata.get("collector_version") or "unknown")
        normalizer_version = str(metadata.get("normalizer_version") or "unknown")
        raw_response_hash = metadata.get("raw_response_hash")

        if evidence_type == "news":
            expected_provider = GDELT_PROVIDER
            expected_source = GDELT_SOURCE
            expected_endpoint = GDELT_GAL_RSS_ENDPOINT
        else:
            expected_provider = CNINFO_PROVIDER
            expected_source = CNINFO_SOURCE
            expected_endpoint = CNINFO_QUERY_ENDPOINT
        source_is_valid = (
            provider == expected_provider
            and source == expected_source
            and endpoint == expected_endpoint
            and not fallback_used
            and usage_status == "review_required"
            and (raw_response_hash is None or bool(HASH_PATTERN.fullmatch(str(raw_response_hash))))
        )
        if evidence_type == "financial_report":
            source_is_valid = source_is_valid and (
                str(metadata.get("provider_category") or "")
                == CNINFO_ANNUAL_REPORT_CATEGORY
            )
        if evidence_type == "news":
            source_is_valid = source_is_valid and (
                str(metadata.get("content_scope") or "") == "title_link_only"
                and metadata.get("feed_window_minutes") == GDELT_RSS_WINDOW_MINUTES
            )
            if supplied_status != "fetch_failed":
                source_is_valid = source_is_valid and (
                    fetched_at is not None
                    and bool(HASH_PATTERN.fullmatch(str(raw_response_hash or "")))
                )
        if not source_is_valid:
            supplied_status = "validation_failed"
            items = []
            evidence_label = _evidence_label(evidence_type)
            failure_reason = f"固定{evidence_label} Provider 血缘、许可状态或 Hash 元数据无效"

        initial_status = (
            supplied_status
            if supplied_status in {"fetch_failed", "validation_failed"}
            else "running"
        )
        batch = {
            "batch_id": batch_id,
            "provider": provider if provider == expected_provider else expected_provider,
            "source": source if source == expected_source else expected_source,
            "fetch_endpoint": endpoint or expected_endpoint,
            "requested_symbols": len(requested),
            "returned_items": len(items),
            "accepted_items": 0,
            "rejected_items": len(items) if initial_status == "validation_failed" else 0,
            "status": initial_status,
            "failure_reason": failure_reason,
            "raw_response_hash": raw_response_hash if source_is_valid else None,
            "collector_version": collector_version,
            "normalizer_version": normalizer_version,
            "usage_status": usage_status if usage_status == "review_required" else "review_required",
            "started_at": started_at,
            "fetched_at": fetched_at,
            "received_at": received_at,
        }
        await self._insert_batch(batch)
        if initial_status in {"fetch_failed", "validation_failed"}:
            return {
                "batch_id": str(batch_id),
                "status": initial_status,
                "accepted_items": 0,
                "rejected_items": len(items),
                "failure_reason": failure_reason,
            }

        rows = [
            self._normalize_item(
                item,
                requested=requested,
                batch_id=batch_id,
                received_at=received_at,
                fetched_at=fetched_at,
                collector_version=collector_version,
                normalizer_version=normalizer_version,
                evidence_type=evidence_type,
            )
            for item in items
        ]
        accepted = sum(row["quality_status"] == "observed" for row in rows)
        rejected = len(rows) - accepted
        if not rows:
            status = "validation_failed"
            evidence_label = _evidence_label(evidence_type)
            failure_reason = failure_reason or f"固定 Provider 未返回{evidence_label}证据"
        elif not accepted:
            status = "validation_failed"
            evidence_label = _evidence_label(evidence_type)
            failure_reason = failure_reason or f"所有{evidence_label}证据均未通过语义校验"
        elif rejected:
            status = "partial"
            evidence_label = _evidence_label(evidence_type)
            failure_reason = failure_reason or f"部分{evidence_label}证据未通过语义校验"
        else:
            status = "success"

        try:
            await self._insert_evidence(rows)
        except Exception as exc:
            failure_reason = f"研究证据与血缘写入失败: {exc}"
            await self._finalize_batch(batch_id, "write_failed", 0, len(rows), failure_reason)
            return {
                "batch_id": str(batch_id),
                "status": "write_failed",
                "accepted_items": 0,
                "rejected_items": len(rows),
                "failure_reason": failure_reason,
            }

        await self._finalize_batch(batch_id, status, accepted, rejected, failure_reason)
        return {
            "batch_id": str(batch_id),
            "status": status,
            "accepted_items": accepted,
            "rejected_items": rejected,
            "failure_reason": failure_reason,
        }

    def _normalize_item(
        self,
        item: dict[str, Any],
        *,
        requested: list[str],
        batch_id: UUID,
        received_at: datetime,
        fetched_at: datetime | None,
        collector_version: str,
        normalizer_version: str,
        evidence_type: str,
    ) -> dict[str, Any]:
        if evidence_type == "announcement":
            return self._normalize_announcement_item(
                item,
                requested=requested,
                batch_id=batch_id,
                received_at=received_at,
                fetched_at=fetched_at,
                collector_version=collector_version,
                normalizer_version=normalizer_version,
            )
        if evidence_type == "financial_report":
            return self._normalize_financial_report_item(
                item,
                requested=requested,
                batch_id=batch_id,
                received_at=received_at,
                fetched_at=fetched_at,
                collector_version=collector_version,
                normalizer_version=normalizer_version,
            )
        if evidence_type == "news":
            return self._normalize_news_item(
                item,
                requested=requested,
                batch_id=batch_id,
                received_at=received_at,
                fetched_at=fetched_at,
                collector_version=collector_version,
                normalizer_version=normalizer_version,
            )
        raise ValueError(f"不支持的研究证据类型：{evidence_type}")

    def _normalize_announcement_item(
        self,
        item: dict[str, Any],
        *,
        requested: list[str],
        batch_id: UUID,
        received_at: datetime,
        fetched_at: datetime | None,
        collector_version: str,
        normalizer_version: str,
    ) -> dict[str, Any]:
        stock_code = str(item.get("stock_code") or (requested[0] if requested else "")).strip().upper()
        source_document_id = str(item.get("source_document_id") or "").strip() or _invalid_document_id(item)
        publisher_name = str(item.get("publisher_name") or "未记录发布者").strip() or "未记录发布者"
        title = str(item.get("title") or "未记录标题").strip() or "未记录标题"
        document_url = str(item.get("document_url") or CNINFO_QUERY_ENDPOINT).strip()
        source_published_date = _parse_date(item.get("source_published_date"))
        raw_hash = str(item.get("raw_hash") or "").strip().lower() or None
        document_bytes = item.get("document_bytes")
        publication_time_precision = str(
            item.get("publication_time_precision") or "unresolved"
        )
        quality_status = str(item.get("quality_status") or "rejected")
        reject_reason = item.get("reject_reason")
        errors: list[str] = []
        if str(item.get("evidence_type") or "") != "announcement":
            errors.append("证据类型不是公告")
        if stock_code not in requested:
            errors.append("公告证券代码不在本批请求范围")
        if not document_url.startswith(CNINFO_DOCUMENT_BASE_URL):
            errors.append("公告原文 URL 不属于固定巨潮原文域名")
        if source_published_date is None:
            errors.append("公告缺少可解析的来源发布日期")
        if publication_time_precision != "date":
            errors.append("公告来源时间精度未明确为日期")
        if quality_status != "observed":
            errors.append(str(reject_reason or "公告原文未通过 Provider 校验"))
        if not raw_hash or not HASH_PATTERN.fullmatch(raw_hash):
            errors.append("公告原文 Hash 无效")
        try:
            document_bytes = int(document_bytes) if document_bytes is not None else None
        except (TypeError, ValueError):
            document_bytes = None
        if document_bytes is None or document_bytes <= 0:
            errors.append("公告原文字节数无效")

        observed = not errors
        return {
            "evidence_id": uuid4(),
            "batch_id": batch_id,
            "evidence_type": "announcement",
            "stock_code": stock_code,
            "source_document_id": source_document_id,
            "provider": CNINFO_PROVIDER,
            "source": CNINFO_SOURCE,
            "publisher_name": publisher_name,
            "title": title,
            "document_url": document_url,
            "source_published_date": source_published_date,
            "source_published_at": None,
            "source_timestamp_raw": item.get("source_timestamp_raw"),
            "publication_time_precision": publication_time_precision
            if publication_time_precision in {"exact", "date", "unresolved"}
            else "unresolved",
            "fetched_at": fetched_at,
            "received_at": received_at,
            "first_observed_at": received_at,
            "available_at": received_at,
            "availability_basis": "system_first_observed",
            "raw_hash": raw_hash if observed else None,
            "document_bytes": document_bytes if observed else None,
            "quality_status": "observed" if observed else "rejected",
            "reject_reason": None if observed else "; ".join(dict.fromkeys(errors)),
            "collector_version": collector_version,
            "normalizer_version": normalizer_version,
            "usage_status": "review_required",
        }

    def _normalize_financial_report_item(
        self,
        item: dict[str, Any],
        *,
        requested: list[str],
        batch_id: UUID,
        received_at: datetime,
        fetched_at: datetime | None,
        collector_version: str,
        normalizer_version: str,
    ) -> dict[str, Any]:
        stock_code = str(item.get("stock_code") or (requested[0] if requested else "")).strip().upper()
        source_document_id = str(item.get("source_document_id") or "").strip() or _invalid_document_id(item)
        publisher_name = str(item.get("publisher_name") or "未记录发布者").strip() or "未记录发布者"
        title = str(item.get("title") or "未记录标题").strip() or "未记录标题"
        normalized_title = re.sub(r"\s+", "", title)
        title_match = ANNUAL_REPORT_TITLE.fullmatch(normalized_title)
        document_url = str(item.get("document_url") or CNINFO_QUERY_ENDPOINT).strip()
        source_published_date = _parse_date(item.get("source_published_date"))
        raw_hash = str(item.get("raw_hash") or "").strip().lower() or None
        document_bytes = item.get("document_bytes")
        publication_time_precision = str(
            item.get("publication_time_precision") or "unresolved"
        )
        quality_status = str(item.get("quality_status") or "rejected")
        reject_reason = item.get("reject_reason")
        report_period_label = item.get("report_period_label")
        errors: list[str] = []
        if str(item.get("evidence_type") or "") != "financial_report":
            errors.append("证据类型不是财报")
        if stock_code not in requested:
            errors.append("财报证券代码不在本批请求范围")
        if not document_url.startswith(CNINFO_DOCUMENT_BASE_URL):
            errors.append("财报原文 URL 不属于固定巨潮原文域名")
        if source_published_date is None:
            errors.append("财报缺少可解析的来源发布日期")
        if publication_time_precision != "date":
            errors.append("财报来源时间精度未明确为日期")
        if str(item.get("provider_category") or "") != CNINFO_ANNUAL_REPORT_CATEGORY:
            errors.append("财报 Provider 分类不符合固定年报分类")
        if str(item.get("provider_category_version") or "") != "cninfo-annual-category-v1":
            errors.append("财报 Provider 分类版本无效")
        if not title_match:
            errors.append("财报标题不是年报全文")
        elif report_period_label != f"{title_match.group('year')}年":
            errors.append("财报报告期标签与标题不一致")
        if str(item.get("report_kind") or "") != "annual":
            errors.append("财报类型不是 annual")
        if item.get("report_period_end") is not None:
            errors.append("财报报告截止日不得在未解析阶段推导")
        if str(item.get("period_precision") or "") != "title_label":
            errors.append("财报期间精度不是 title_label")
        if str(item.get("document_role") or "") != "full_report":
            errors.append("财报文档角色不是全文")
        for field in (
            "consolidation_scope",
            "currency_code",
            "currency_unit",
            "audit_opinion",
        ):
            if str(item.get(field) or "") != "unresolved":
                errors.append(f"财报字段 {field} 在未解析阶段必须为 unresolved")
        if str(item.get("revision_status") or "") != "none":
            errors.append("财报修订关系未通过验证")
        if item.get("supersedes_evidence_id") is not None:
            errors.append("财报未验证修订关系不得指定被替代证据")
        if str(item.get("detail_parse_status") or "") != "metadata_observed":
            errors.append("财报详情解析状态无效")
        if quality_status != "observed":
            errors.append(str(reject_reason or "财报原文未通过 Provider 校验"))
        if not raw_hash or not HASH_PATTERN.fullmatch(raw_hash):
            errors.append("财报原文 Hash 无效")
        try:
            document_bytes = int(document_bytes) if document_bytes is not None else None
        except (TypeError, ValueError):
            document_bytes = None
        if document_bytes is None or document_bytes <= 0:
            errors.append("财报原文字节数无效")

        observed = not errors
        financial_detail = None
        if observed:
            financial_detail = {
                "provider_category": CNINFO_ANNUAL_REPORT_CATEGORY,
                "provider_category_version": "cninfo-annual-category-v1",
                "source_title_raw": title,
                "report_kind": "annual",
                "report_period_label": report_period_label,
                "report_period_end": None,
                "period_precision": "title_label",
                "document_role": "full_report",
                "consolidation_scope": "unresolved",
                "currency_code": "unresolved",
                "currency_unit": "unresolved",
                "audit_opinion": "unresolved",
                "revision_status": "none",
                "supersedes_evidence_id": None,
                "detail_parse_status": "metadata_observed",
            }
        return {
            "evidence_id": uuid4(),
            "batch_id": batch_id,
            "evidence_type": "financial_report",
            "stock_code": stock_code,
            "source_document_id": source_document_id,
            "provider": CNINFO_PROVIDER,
            "source": CNINFO_SOURCE,
            "publisher_name": publisher_name,
            "title": title,
            "document_url": document_url,
            "source_published_date": source_published_date,
            "source_published_at": None,
            "source_timestamp_raw": item.get("source_timestamp_raw"),
            "publication_time_precision": publication_time_precision
            if publication_time_precision in {"exact", "date", "unresolved"}
            else "unresolved",
            "fetched_at": fetched_at,
            "received_at": received_at,
            "first_observed_at": received_at,
            "available_at": received_at,
            "availability_basis": "system_first_observed",
            "raw_hash": raw_hash if observed else None,
            "document_bytes": document_bytes if observed else None,
            "quality_status": "observed" if observed else "rejected",
            "reject_reason": None if observed else "; ".join(dict.fromkeys(errors)),
            "collector_version": collector_version,
            "normalizer_version": normalizer_version,
            "usage_status": "review_required",
            "financial_detail": financial_detail,
        }

    def _normalize_news_item(
        self,
        item: dict[str, Any],
        *,
        requested: list[str],
        batch_id: UUID,
        received_at: datetime,
        fetched_at: datetime | None,
        collector_version: str,
        normalizer_version: str,
    ) -> dict[str, Any]:
        stock_code = str(item.get("stock_code") or (requested[0] if requested else "")).strip().upper()
        source_document_id = str(item.get("source_document_id") or "").strip() or _invalid_document_id(item)
        publisher_name = str(item.get("publisher_name") or "未记录发布域名").strip() or "未记录发布域名"
        title = str(item.get("title") or "未记录标题").strip() or "未记录标题"
        document_url = str(item.get("document_url") or "").strip()
        raw_hash = str(item.get("raw_hash") or "").strip().lower() or None
        document_bytes = item.get("document_bytes")
        source_timestamp_raw = str(item.get("source_timestamp_raw") or "").strip() or None
        source_title_raw = str(item.get("source_title_raw") or "").strip()
        publisher_domain = str(item.get("publisher_domain") or "").strip().lower()
        provider_reported_at = _parse_iso(item.get("provider_reported_at"))
        quality_status = str(item.get("quality_status") or "rejected")
        reject_reason = item.get("reject_reason")
        parsed_url = urlparse(document_url)
        expected_document_id = (
            f"gdelt-gal:{hashlib.sha256(document_url.encode('utf-8')).hexdigest()}"
            if document_url
            else ""
        )
        errors: list[str] = []
        if str(item.get("evidence_type") or "") != "news":
            errors.append("证据类型不是新闻")
        if stock_code not in requested:
            errors.append("新闻证券代码不在本批请求范围")
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
            errors.append("新闻原文链接无效")
        if document_url == GDELT_GAL_RSS_ENDPOINT:
            errors.append("新闻原文链接不得回填为 GDELT RSS 地址")
        if source_document_id != expected_document_id:
            errors.append("新闻文档标识未与原文链接绑定")
        if publisher_name != publisher_domain or publisher_domain != str(parsed_url.hostname or "").lower():
            errors.append("新闻发布域名与原文链接不一致")
        if source_title_raw != title:
            errors.append("新闻原始标题与展示标题不一致")
        if item.get("source_published_date") is not None or item.get("source_published_at") is not None:
            errors.append("新闻不得将 GDELT 时间写为来源发布时间")
        if str(item.get("publication_time_precision") or "") != "unresolved":
            errors.append("新闻来源时间精度必须为 unresolved")
        if source_timestamp_raw is None or provider_reported_at is None:
            errors.append("新闻缺少可解析的 GDELT Provider 时间")
        if str(item.get("provider_feed_url") or "") != GDELT_GAL_RSS_ENDPOINT:
            errors.append("新闻 Provider RSS 地址不符合固定来源")
        if str(item.get("provider_time_semantics") or "") != "publication_or_first_seen":
            errors.append("新闻 Provider 时间语义无效")
        if str(item.get("association_method") or "") != "title_alias_match":
            errors.append("新闻关联方法不是标题别名匹配")
        if not str(item.get("association_alias") or "").strip():
            errors.append("新闻缺少匹配别名")
        if str(item.get("association_status") or "") != "review_required":
            errors.append("新闻关联状态被错误放宽")
        if str(item.get("content_scope") or "") != "title_link_only":
            errors.append("新闻内容范围不是 title_link_only")
        if item.get("feed_window_minutes") != GDELT_RSS_WINDOW_MINUTES:
            errors.append("新闻 RSS 窗口语义无效")
        if str(item.get("raw_representation") or "") != "rss_item_xml_reserialized":
            errors.append("新闻 Hash 原始表示语义无效")
        if str(item.get("detail_parse_status") or "") != "metadata_observed":
            errors.append("新闻详情解析状态无效")
        if quality_status != "observed":
            errors.append(str(reject_reason or "新闻 RSS 条目未通过 Provider 校验"))
        if not raw_hash or not HASH_PATTERN.fullmatch(raw_hash):
            errors.append("新闻 RSS 条目 Hash 无效")
        try:
            document_bytes = int(document_bytes) if document_bytes is not None else None
        except (TypeError, ValueError):
            document_bytes = None
        if document_bytes is None or document_bytes <= 0:
            errors.append("新闻 RSS 条目字节数无效")

        observed = not errors
        news_detail = None
        if observed:
            news_detail = {
                "provider_feed_url": GDELT_GAL_RSS_ENDPOINT,
                "source_title_raw": source_title_raw,
                "publisher_domain": publisher_domain,
                "provider_reported_at": provider_reported_at,
                "provider_time_semantics": "publication_or_first_seen",
                "association_method": "title_alias_match",
                "association_alias": str(item.get("association_alias")).strip(),
                "association_status": "review_required",
                "content_scope": "title_link_only",
                "feed_window_minutes": GDELT_RSS_WINDOW_MINUTES,
                "raw_representation": "rss_item_xml_reserialized",
                "detail_parse_status": "metadata_observed",
            }
        return {
            "evidence_id": uuid4(),
            "batch_id": batch_id,
            "evidence_type": "news",
            "stock_code": stock_code,
            "source_document_id": source_document_id,
            "provider": GDELT_PROVIDER,
            "source": GDELT_SOURCE,
            "publisher_name": publisher_name,
            "title": title,
            "document_url": document_url or GDELT_GAL_RSS_ENDPOINT,
            "source_published_date": None,
            "source_published_at": None,
            "source_timestamp_raw": source_timestamp_raw,
            "publication_time_precision": "unresolved",
            "fetched_at": fetched_at,
            "received_at": received_at,
            "first_observed_at": received_at,
            "available_at": received_at,
            "availability_basis": "system_first_observed",
            "raw_hash": raw_hash if observed else None,
            "document_bytes": document_bytes if observed else None,
            "quality_status": "observed" if observed else "rejected",
            "reject_reason": None if observed else "; ".join(dict.fromkeys(errors)),
            "collector_version": collector_version,
            "normalizer_version": normalizer_version,
            "usage_status": "review_required",
            "news_detail": news_detail,
        }

    async def _insert_batch(self, batch: dict[str, Any]) -> None:
        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO market.research_evidence_batches (
                        batch_id, provider, source, fetch_endpoint, requested_symbols,
                        returned_items, accepted_items, rejected_items, status, failure_reason,
                        raw_response_hash, collector_version, normalizer_version, usage_status,
                        started_at, fetched_at, received_at
                    ) VALUES (
                        :batch_id, :provider, :source, :fetch_endpoint, :requested_symbols,
                        :returned_items, :accepted_items, :rejected_items, :status, :failure_reason,
                        :raw_response_hash, :collector_version, :normalizer_version, :usage_status,
                        :started_at, :fetched_at, :received_at
                    )
                    """
                ),
                batch,
            )
            await session.commit()

    async def _insert_evidence(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        async with self._session_factory() as session:
            for row in rows:
                result = await session.execute(
                    text(
                        """
                        INSERT INTO market.research_evidence (
                            evidence_id, batch_id, evidence_type, stock_code, source_document_id,
                            provider, source, publisher_name, title, document_url,
                            source_published_date, source_published_at, source_timestamp_raw,
                            publication_time_precision, fetched_at, received_at, first_observed_at,
                            available_at, availability_basis, raw_hash, document_bytes, quality_status,
                            reject_reason, fallback_used, collector_version, normalizer_version,
                            usage_status
                        ) VALUES (
                            :evidence_id, :batch_id, :evidence_type, :stock_code, :source_document_id,
                            :provider, :source, :publisher_name, :title, :document_url,
                            :source_published_date, :source_published_at, :source_timestamp_raw,
                            :publication_time_precision, :fetched_at, :received_at, :first_observed_at,
                            :available_at, :availability_basis, :raw_hash, :document_bytes, :quality_status,
                            :reject_reason, FALSE, :collector_version, :normalizer_version,
                            :usage_status
                        ) ON CONFLICT (provider, source_document_id, raw_hash) DO NOTHING
                        RETURNING evidence_id
                        """
                    ),
                    row,
                )
                financial_detail = row.get("financial_detail")
                news_detail = row.get("news_detail")
                if financial_detail or news_detail:
                    evidence_id = result.scalar_one_or_none()
                    if evidence_id is None:
                        existing = await session.execute(
                            text(
                                """
                                SELECT evidence_id
                                FROM market.research_evidence
                                WHERE provider = :provider
                                  AND source_document_id = :source_document_id
                                  AND raw_hash = :raw_hash
                                """
                            ),
                            row,
                        )
                        evidence_id = existing.scalar_one_or_none()
                    if evidence_id is None:
                        raise RuntimeError("无法解析已存在研究证据的证据 ID")
                if financial_detail:
                    await session.execute(
                        text(
                            """
                            INSERT INTO market.research_financial_report_details (
                                evidence_id, provider_category, provider_category_version,
                                source_title_raw, report_kind, report_period_label,
                                report_period_end, period_precision, document_role,
                                consolidation_scope, currency_code, currency_unit,
                                audit_opinion, revision_status, supersedes_evidence_id,
                                detail_parse_status
                            ) VALUES (
                                :evidence_id, :provider_category, :provider_category_version,
                                :source_title_raw, :report_kind, :report_period_label,
                                :report_period_end, :period_precision, :document_role,
                                :consolidation_scope, :currency_code, :currency_unit,
                                :audit_opinion, :revision_status, :supersedes_evidence_id,
                                :detail_parse_status
                            ) ON CONFLICT (evidence_id) DO NOTHING
                            """
                        ),
                        {**financial_detail, "evidence_id": evidence_id},
                    )
                if news_detail:
                    await session.execute(
                        text(
                            """
                            INSERT INTO market.research_news_details (
                                evidence_id, provider_feed_url, source_title_raw,
                                publisher_domain, provider_reported_at,
                                provider_time_semantics, association_method,
                                association_alias, association_status, content_scope,
                                feed_window_minutes, raw_representation,
                                detail_parse_status
                            ) VALUES (
                                :evidence_id, :provider_feed_url, :source_title_raw,
                                :publisher_domain, :provider_reported_at,
                                :provider_time_semantics, :association_method,
                                :association_alias, :association_status, :content_scope,
                                :feed_window_minutes, :raw_representation,
                                :detail_parse_status
                            ) ON CONFLICT (evidence_id) DO NOTHING
                            """
                        ),
                        {**news_detail, "evidence_id": evidence_id},
                    )
            await session.commit()

    async def _finalize_batch(
        self,
        batch_id: UUID,
        status: str,
        accepted_items: int,
        rejected_items: int,
        failure_reason: str | None,
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    UPDATE market.research_evidence_batches
                    SET status = :status,
                        accepted_items = :accepted_items,
                        rejected_items = :rejected_items,
                        failure_reason = :failure_reason
                    WHERE batch_id = :batch_id
                    """
                ),
                {
                    "batch_id": batch_id,
                    "status": status,
                    "accepted_items": accepted_items,
                    "rejected_items": rejected_items,
                    "failure_reason": failure_reason,
                },
            )
            await session.commit()
