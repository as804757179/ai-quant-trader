import hashlib
import json
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.core.config import settings
from app.core.auth import get_request_principal
from app.core.response import error, ok
from app.data.research_evidence_profiles import ResearchEvidenceRequirementProfile
from app.data.research_evidence_readiness import ResearchEvidenceReadinessService
from app.db import get_db

router = APIRouter()


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def serialize_review(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in row.items()}


class NewsEvidenceManualReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conclusion: Literal[
        "title_link_relevant",
        "title_link_irrelevant",
        "needs_more_evidence",
    ]
    reason: str = Field(min_length=1, max_length=2000)


def _news_review_request_hash(evidence_id: UUID, body: NewsEvidenceManualReviewRequest) -> str:
    payload = {
        "evidence_id": str(evidence_id),
        "conclusion": body.conclusion,
        "reason": body.reason.strip(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _research_candidate_snapshot_hash(
    items: list[dict[str, Any]], counts: dict[str, int], published: bool
) -> str:
    payload = {
        "items": items,
        "counts": counts,
        "candidate_status": "published" if published else "release_locked",
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def _find_reviewable_news_evidence(
    db: Any, evidence_id: UUID
) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT evidence.evidence_id::text AS evidence_id, evidence.stock_code,
                   evidence.title, evidence.document_url, evidence.usage_status
            FROM market.research_evidence AS evidence
            INNER JOIN market.research_news_details AS news_detail
                ON news_detail.evidence_id = evidence.evidence_id
            WHERE evidence.evidence_id = :evidence_id
              AND evidence.evidence_type = 'news'
              AND evidence.quality_status = 'observed'
              AND evidence.usage_status = 'review_required'
            """
        ),
        {"evidence_id": evidence_id},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row else None


async def _find_observed_financial_location_evidence(
    db: Any, evidence_id: UUID
) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT evidence.evidence_id::text AS evidence_id, evidence.stock_code,
                   evidence.title, evidence.raw_hash, evidence.available_at,
                   evidence.usage_status,
                   snapshot.snapshot_id::text AS snapshot_id,
                   snapshot.observed_raw_hash, snapshot.observed_bytes,
                   parse_run.parse_run_id::text AS parse_run_id,
                   parse_run.parser_name, parse_run.parser_version,
                   parse_run.normalization_version, parse_run.status AS parse_status,
                   parse_run.page_count, parse_run.text_page_count, parse_run.completed_at
            FROM market.research_evidence AS evidence
            LEFT JOIN LATERAL (
                SELECT item.*
                FROM market.research_financial_report_snapshots AS item
                WHERE item.evidence_id = evidence.evidence_id
                  AND item.status = 'observed'
                ORDER BY item.created_at DESC, item.snapshot_id DESC
                LIMIT 1
            ) AS snapshot ON TRUE
            LEFT JOIN LATERAL (
                SELECT item.*
                FROM market.research_financial_report_parse_runs AS item
                WHERE item.snapshot_id = snapshot.snapshot_id
                  AND item.status IN ('success', 'partial')
                ORDER BY item.completed_at DESC, item.parse_run_id DESC
                LIMIT 1
            ) AS parse_run ON TRUE
            WHERE evidence.evidence_id = :evidence_id
              AND evidence.evidence_type = 'financial_report'
              AND evidence.quality_status = 'observed'
              AND evidence.usage_status = 'review_required'
            """
        ),
        {"evidence_id": evidence_id},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row else None


async def _load_source_usage_context(db: Any) -> dict[tuple[str, str], dict[str, Any]]:
    result = await db.execute(
        text(
            """
            WITH latest_terms AS (
                SELECT DISTINCT ON (provider, source, terms_url)
                       terms_evidence_id, provider, source, source_scope,
                       document_kind, terms_url, retrieved_at, source_effective_at,
                       source_time_precision, raw_hash, document_bytes, content_type,
                       status, failure_reason, collector_version, created_at
                FROM market.research_source_terms_evidence
                ORDER BY provider, source, terms_url,
                         created_at DESC, terms_evidence_id DESC
            )
            SELECT terms.terms_evidence_id::text AS terms_evidence_id,
                   terms.provider, terms.source, terms.source_scope,
                   terms.document_kind, terms.terms_url, terms.retrieved_at,
                   terms.source_effective_at, terms.source_time_precision,
                   terms.raw_hash, terms.document_bytes, terms.content_type,
                   terms.status, terms.failure_reason, terms.collector_version,
                   terms.created_at,
                   review.review_id::text AS review_id,
                   review.usage_scope, review.decision_status, review.reason,
                   review.reviewer_label, review.identity_assurance,
                   review.policy_version, review.reviewed_at
            FROM latest_terms AS terms
            LEFT JOIN market.research_source_usage_reviews AS review
                ON review.terms_evidence_id = terms.terms_evidence_id
            ORDER BY terms.provider, terms.source,
                     review.reviewed_at DESC NULLS LAST, review.review_id DESC,
                     terms.terms_url, terms.terms_evidence_id
            """
        )
    )
    contexts: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_row in result.mappings().all():
        row = dict(raw_row)
        key = (str(row["provider"]), str(row["source"]))
        context = contexts.setdefault(
            key,
            {
                "provider": key[0],
                "source": key[1],
                "source_scope": row["source_scope"],
                "terms_evidence": [],
                "review_history": [],
                "_terms_ids": set(),
                "_review_ids": set(),
            },
        )
        terms_evidence_id = str(row["terms_evidence_id"])
        if terms_evidence_id not in context["_terms_ids"]:
            context["_terms_ids"].add(terms_evidence_id)
            context["terms_evidence"].append(
                serialize_review(
                    {
                        "terms_evidence_id": terms_evidence_id,
                        "document_kind": row["document_kind"],
                        "terms_url": row["terms_url"],
                        "retrieved_at": row["retrieved_at"],
                        "source_effective_at": row["source_effective_at"],
                        "source_time_precision": row["source_time_precision"],
                        "raw_hash": row["raw_hash"],
                        "document_bytes": row["document_bytes"],
                        "content_type": row["content_type"],
                        "status": row["status"],
                        "failure_reason": row["failure_reason"],
                        "collector_version": row["collector_version"],
                        "created_at": row["created_at"],
                    }
                )
            )
        if row["review_id"] and row["review_id"] not in context["_review_ids"]:
            context["_review_ids"].add(row["review_id"])
            context["review_history"].append(
                serialize_review(
                    {
                        "review_id": row["review_id"],
                        "terms_evidence_id": terms_evidence_id,
                        "usage_scope": row["usage_scope"],
                        "decision_status": row["decision_status"],
                        "reason": row["reason"],
                        "reviewer_label": row["reviewer_label"],
                        "identity_assurance": row["identity_assurance"],
                        "policy_version": row["policy_version"],
                        "reviewed_at": row["reviewed_at"],
                    }
                )
            )
    for context in contexts.values():
        context["terms_evidence"].sort(
            key=lambda item: (
                str(item["terms_url"]),
                str(item["created_at"] or ""),
                str(item["terms_evidence_id"]),
            )
        )
        context["review_history"].sort(
            key=lambda review: (
                review["reviewed_at"] is not None,
                str(review["reviewed_at"] or ""),
                str(review["review_id"]),
            ),
            reverse=True,
        )
        latest_reviews: dict[str, dict[str, Any]] = {}
        latest_reviews_by_terms: dict[str, dict[str, dict[str, Any]]] = {}
        for review in context["review_history"]:
            usage_scope = str(review["usage_scope"])
            latest_reviews.setdefault(usage_scope, review)
            latest_reviews_by_terms.setdefault(
                str(review["terms_evidence_id"]), {}
            ).setdefault(usage_scope, review)
        context["latest_reviews"] = latest_reviews
        context["precheck_status"] = (
            "rejected"
            if any(
                review["decision_status"] == "rejected"
                for reviews in latest_reviews_by_terms.values()
                for review in reviews.values()
            )
            else "review_required"
        )
        context["authorization_granted"] = False
        del context["_terms_ids"]
        del context["_review_ids"]
    return contexts


def _source_usage_reference(context: dict[str, Any] | None) -> dict[str, Any]:
    if not context:
        return {
            "precheck_status": "review_required",
            "authorization_granted": False,
            "terms_evidence": [],
            "latest_reviews": {},
        }
    return {
        "provider": context["provider"],
        "source": context["source"],
        "source_scope": context["source_scope"],
        "precheck_status": context["precheck_status"],
        "authorization_granted": False,
        "terms_evidence": [
            {
                "terms_evidence_id": item["terms_evidence_id"],
                "terms_url": item["terms_url"],
                "raw_hash": item["raw_hash"],
                "status": item["status"],
            }
            for item in context["terms_evidence"]
        ],
        "latest_reviews": {
            usage_scope: {
                "review_id": review["review_id"],
                "terms_evidence_id": review["terms_evidence_id"],
                "decision_status": review["decision_status"],
                "identity_assurance": review["identity_assurance"],
                "policy_version": review["policy_version"],
            }
            for usage_scope, review in context["latest_reviews"].items()
        },
    }


@router.get("/source-usage-evidence")
async def list_research_source_usage_evidence(
    provider: Literal["cninfo", "gdelt"] | None = Query(None),
    source: Literal[
        "cninfo_listed_company_disclosure", "gdelt_article_list_rss"
    ]
    | None = Query(None),
):
    """只读查询固定来源的条款证据和许可预审历史。"""
    async with get_db() as db:
        contexts = await _load_source_usage_context(db)
    items = [
        context
        for key, context in sorted(contexts.items())
        if (provider is None or key[0] == provider)
        and (source is None or key[1] == source)
    ]
    return ok(
        {
            "items": items,
            "total": len(items),
            "observed_only": True,
            "research_readiness": "not_granted",
            "authorization_granted": False,
            "tradable": False,
            "order_created": False,
            "source": (
                "market.research_source_terms_evidence+"
                "market.research_source_usage_reviews"
            ),
            "source_version": "research-source-usage-evidence-v2",
        }
    )


@router.get("/readiness")
async def list_readiness_reviews(
    stock_code: str | None = Query(None),
    readiness_status: str | None = Query(
        None, pattern="^(ready|review_required|rejected)$"
    ),
    research_use_scope: str | None = Query(None),
    requirement_profile: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """按完整授权维度只读查询 Research Readiness 审核。"""
    filters = ["1=1"]
    params: dict[str, Any] = {}
    if stock_code:
        filters.append("stock_code = :stock_code")
        params["stock_code"] = stock_code.strip().upper()
    if readiness_status:
        filters.append("readiness_status = :readiness_status")
        params["readiness_status"] = readiness_status
    if research_use_scope:
        filters.append("research_use_scope = :research_use_scope")
        params["research_use_scope"] = research_use_scope
    if requirement_profile:
        filters.append("requirement_profile = :requirement_profile")
        params["requirement_profile"] = requirement_profile
    if date_from:
        filters.append("date_to >= :date_from")
        params["date_from"] = date_from
    if date_to:
        filters.append("date_from <= :date_to")
        params["date_to"] = date_to

    where_clause = " AND ".join(filters)
    params.update({"limit": page_size, "offset": (page - 1) * page_size})
    async with get_db() as db:
        summary_result = await db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE readiness_status='ready') AS ready,
                       COUNT(*) FILTER (WHERE readiness_status='review_required') AS review_required,
                       COUNT(*) FILTER (WHERE readiness_status='rejected') AS rejected,
                       COUNT(DISTINCT stock_code) AS stock_count,
                       COALESCE(SUM(jsonb_array_length(unresolved_fields)), 0)
                           AS unresolved_field_count,
                       COALESCE(SUM(jsonb_array_length(rejected_fields)), 0)
                           AS rejected_field_count,
                       MAX(reviewed_at) AS latest_reviewed_at,
                       ARRAY_AGG(DISTINCT policy_version ORDER BY policy_version)
                           FILTER (WHERE policy_version IS NOT NULL) AS policy_versions
                FROM market.research_readiness_reviews
                WHERE {where_clause}
                """
            ),
            params,
        )
        summary = dict(summary_result.mappings().one())
        rows = await db.execute(
            text(
                f"""
                SELECT review_id, stock_code, period, date_from, date_to, adjustment,
                       readiness_status, research_use_scope, requirement_profile,
                       required_fields, validated_fields, unresolved_fields,
                       rejected_fields, corporate_action_status, missingness_status,
                       provider_validation_status, review_reason, policy_version,
                       reviewer_version, reviewed_at
                FROM market.research_readiness_reviews
                WHERE {where_clause}
                ORDER BY stock_code, date_from DESC, requirement_profile, reviewed_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [serialize_review(dict(row)) for row in rows.mappings().all()]
        dimension_result = await db.execute(
            text(
                f"""
                SELECT 'profile' AS dimension, requirement_profile AS value, COUNT(*) AS count
                FROM market.research_readiness_reviews
                WHERE {where_clause}
                GROUP BY requirement_profile
                UNION ALL
                SELECT 'provider_validation', provider_validation_status, COUNT(*)
                FROM market.research_readiness_reviews
                WHERE {where_clause}
                GROUP BY provider_validation_status
                UNION ALL
                SELECT 'missingness', missingness_status, COUNT(*)
                FROM market.research_readiness_reviews
                WHERE {where_clause}
                GROUP BY missingness_status
                UNION ALL
                SELECT 'corporate_action', corporate_action_status, COUNT(*)
                FROM market.research_readiness_reviews
                WHERE {where_clause}
                GROUP BY corporate_action_status
                """
            ),
            params,
        )
        dimensions: dict[str, dict[str, int]] = {}
        for row in dimension_result.mappings().all():
            dimensions.setdefault(str(row["dimension"]), {})[
                str(row["value"] or "not_recorded")
            ] = int(row["count"] or 0)
        blocker_result = await db.execute(
            text(
                f"""
                SELECT COALESCE(NULLIF(review_reason, ''), '未记录') AS reason,
                       COUNT(*) AS count
                FROM market.research_readiness_reviews
                WHERE {where_clause}
                  AND readiness_status <> 'ready'
                GROUP BY COALESCE(NULLIF(review_reason, ''), '未记录')
                ORDER BY count DESC, reason
                LIMIT 10
                """
            ),
            params,
        )
        blockers = [dict(row) for row in blocker_result.mappings().all()]

    return ok(
        {
            "items": items,
            "total": int(summary["total"] or 0),
            "summary": {
                "ready": int(summary["ready"] or 0),
                "review_required": int(summary["review_required"] or 0),
                "rejected": int(summary["rejected"] or 0),
                "stock_count": int(summary["stock_count"] or 0),
                "unresolved_field_count": int(
                    summary["unresolved_field_count"] or 0
                ),
                "rejected_field_count": int(summary["rejected_field_count"] or 0),
                "latest_reviewed_at": _json_value(summary["latest_reviewed_at"]),
                "policy_versions": summary["policy_versions"] or [],
            },
            "dimensions": dimensions,
            "blockers": blockers,
            "observed_only": True,
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "page": page,
            "page_size": page_size,
            "source": "market.research_readiness_reviews",
            "source_version": "field-readiness-v2",
        }
    )


@router.get("/evidence")
async def list_research_evidence(
    stock_code: str | None = Query(None),
    evidence_type: str | None = Query(
        None, pattern="^(announcement|news|financial_report)$"
    ),
    quality_status: str | None = Query(None, pattern="^(observed|rejected)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    filters = ["1=1"]
    params: dict[str, Any] = {}
    if stock_code:
        filters.append("evidence.stock_code = :stock_code")
        params["stock_code"] = stock_code.strip().upper()
    if evidence_type:
        filters.append("evidence.evidence_type = :evidence_type")
        params["evidence_type"] = evidence_type
    if quality_status:
        filters.append("evidence.quality_status = :quality_status")
        params["quality_status"] = quality_status
    where_clause = " AND ".join(filters)
    params.update({"limit": page_size, "offset": (page - 1) * page_size})
    async with get_db() as db:
        summary_result = await db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE quality_status='observed') AS observed,
                       COUNT(*) FILTER (WHERE quality_status='rejected') AS rejected,
                       COUNT(DISTINCT stock_code) AS stock_count,
                       MAX(available_at) AS latest_available_at,
                       ARRAY_AGG(DISTINCT usage_status ORDER BY usage_status) AS usage_statuses
                FROM market.research_evidence AS evidence
                WHERE {where_clause}
                """
            ),
            params,
        )
        summary = dict(summary_result.mappings().one())
        result = await db.execute(
            text(
                f"""
                SELECT evidence.evidence_id::text AS evidence_id,
                       evidence.batch_id::text AS batch_id,
                       evidence.evidence_type, evidence.stock_code,
                       evidence.source_document_id, evidence.provider, evidence.source,
                       evidence.publisher_name, evidence.title, evidence.document_url,
                       evidence.source_published_date, evidence.source_published_at,
                       evidence.source_timestamp_raw, evidence.publication_time_precision,
                       evidence.fetched_at, evidence.received_at, evidence.first_observed_at,
                       evidence.available_at, evidence.availability_basis, evidence.raw_hash,
                       evidence.document_bytes, evidence.quality_status, evidence.reject_reason,
                       evidence.fallback_used, evidence.collector_version,
                       evidence.normalizer_version, evidence.usage_status,
                       news_detail.provider_reported_at,
                       CASE
                           WHEN latest_news_review.review_id IS NOT NULL
                           THEN jsonb_build_object(
                               'review_id', latest_news_review.review_id,
                               'reviewer_label', latest_news_review.reviewer_label,
                               'conclusion', latest_news_review.conclusion,
                               'reviewed_at', latest_news_review.reviewed_at
                           )
                           ELSE NULL
                       END AS manual_review
                FROM market.research_evidence AS evidence
                LEFT JOIN market.research_news_details AS news_detail
                    ON news_detail.evidence_id = evidence.evidence_id
                LEFT JOIN LATERAL (
                    SELECT news_review.review_id, news_review.reviewer_label,
                           news_review.conclusion, news_review.reviewed_at
                    FROM market.research_news_evidence_reviews AS news_review
                    WHERE news_review.evidence_id = evidence.evidence_id
                    ORDER BY news_review.reviewed_at DESC, news_review.review_id DESC
                    LIMIT 1
                ) AS latest_news_review ON TRUE
                WHERE {where_clause}
                ORDER BY evidence.available_at DESC, evidence.evidence_id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [serialize_review(dict(row)) for row in result.mappings().all()]
    return ok(
        {
            "items": items,
            "total": int(summary["total"] or 0),
            "summary": {
                "observed": int(summary["observed"] or 0),
                "rejected": int(summary["rejected"] or 0),
                "stock_count": int(summary["stock_count"] or 0),
                "latest_available_at": _json_value(summary["latest_available_at"]),
                "usage_statuses": summary["usage_statuses"] or [],
            },
            "observed_only": True,
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "page": page,
            "page_size": page_size,
            "source": "market.research_evidence",
            "source_version": "research-evidence-observation-v2",
        }
    )


@router.get("/evidence/readiness-audit")
async def list_research_evidence_readiness_audit(
    research_use_scope: str = Query(...),
    requirement_profile: str = Query(...),
    required_fields: list[str] | None = Query(None),
    stock_code: str | None = Query(None),
    evidence_type: str | None = Query(
        None, pattern="^(announcement|news|financial_report)$"
    ),
    evidence_id: UUID | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """只读执行多维证据资格预审；不授予 Research Readiness。"""
    scope = research_use_scope.strip()
    profile_name = requirement_profile.strip()
    declared_fields = [field.strip() for field in (required_fields or [])]
    try:
        profile = ResearchEvidenceRequirementProfile.get(profile_name)
        profile.validate_declaration(
            research_use_scope=scope,
            required_fields=declared_fields,
        )
    except ValueError:
        error(
            "多维证据资格预审的用途、Profile 或必需字段声明不匹配",
            "INVALID_EVIDENCE_READINESS_DECLARATION",
            422,
        )
    if evidence_type and evidence_type != profile.evidence_type:
        error(
            "证据类型与 Requirement Profile 不匹配",
            "EVIDENCE_PROFILE_TYPE_MISMATCH",
            422,
        )

    filters = ["evidence.evidence_type = :profile_evidence_type"]
    params: dict[str, Any] = {"profile_evidence_type": profile.evidence_type}
    if stock_code:
        filters.append("evidence.stock_code = :stock_code")
        params["stock_code"] = stock_code.strip().upper()
    if evidence_id:
        filters.append("evidence.evidence_id = :evidence_id")
        params["evidence_id"] = str(evidence_id)
    where_clause = " AND ".join(filters)
    params.update({"limit": page_size, "offset": (page - 1) * page_size})

    async with get_db() as db:
        total_result = await db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total
                FROM market.research_evidence AS evidence
                WHERE {where_clause}
                """
            ),
            params,
        )
        total = int(total_result.mappings().one()["total"] or 0)
        result = await db.execute(
            text(
                f"""
                SELECT evidence.evidence_id::text AS evidence_id,
                       evidence.evidence_type, evidence.stock_code,
                       evidence.provider, evidence.source,
                       evidence.source_document_id, evidence.source_published_at,
                       evidence.publication_time_precision, evidence.available_at,
                       evidence.raw_hash, evidence.quality_status, evidence.usage_status,
                       financial_detail.report_period_end AS financial_report_period_end,
                       financial_detail.consolidation_scope AS financial_consolidation_scope,
                       financial_detail.currency_code AS financial_currency_code,
                       financial_detail.currency_unit AS financial_currency_unit,
                       financial_detail.audit_opinion AS financial_audit_opinion,
                       financial_detail.revision_status AS financial_revision_status,
                       financial_detail.supersedes_evidence_id::text
                           AS financial_supersedes_evidence_id,
                       financial_detail.detail_parse_status
                           AS financial_detail_parse_status,
                       news_detail.raw_representation AS news_raw_representation,
                       latest_news_review.review_id::text AS latest_news_review_id,
                       latest_news_review.conclusion AS latest_news_review_conclusion
                FROM market.research_evidence AS evidence
                LEFT JOIN market.research_financial_report_details AS financial_detail
                    ON financial_detail.evidence_id = evidence.evidence_id
                LEFT JOIN market.research_news_details AS news_detail
                    ON news_detail.evidence_id = evidence.evidence_id
                LEFT JOIN LATERAL (
                    SELECT news_review.review_id, news_review.conclusion
                    FROM market.research_news_evidence_reviews AS news_review
                    WHERE news_review.evidence_id = evidence.evidence_id
                    ORDER BY news_review.reviewed_at DESC, news_review.review_id DESC
                    LIMIT 1
                ) AS latest_news_review ON TRUE
                WHERE {where_clause}
                ORDER BY evidence.available_at DESC, evidence.evidence_id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        source_usage_contexts = await _load_source_usage_context(db)
        items = []
        for row in result.mappings().all():
            evidence = dict(row)
            evidence["source_usage_evidence"] = _source_usage_reference(
                source_usage_contexts.get(
                    (str(evidence["provider"]), str(evidence["source"]))
                )
            )
            items.append(
                ResearchEvidenceReadinessService.evaluate(
                    evidence,
                    research_use_scope=scope,
                    requirement_profile=profile.name,
                    required_fields=declared_fields,
                ).to_payload()
            )

    return ok(
        {
            "items": items,
            "total": total,
            "research_use_scope": scope,
            "requirement_profile": profile.name,
            "required_fields": list(declared_fields),
            "policy_version": profile.policy_version,
            "observed_only": True,
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "page": page,
            "page_size": page_size,
            "source": "market.research_evidence",
            "source_version": "multidimensional-evidence-readiness-audit-v1",
        }
    )


@router.get("/evidence/batches")
async def list_research_evidence_batches(
    limit: int | None = Query(None, ge=1, le=100, description="兼容旧客户端"),
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
):
    resolved_page_size = page_size or limit or 20
    offset = (page - 1) * resolved_page_size
    async with get_db() as db:
        total_result = await db.execute(
            text("SELECT COUNT(*) AS total FROM market.research_evidence_batches")
        )
        total = int(total_result.mappings().one()["total"] or 0)
        result = await db.execute(
            text(
                """
                SELECT batch_id::text AS batch_id, provider, source, fetch_endpoint,
                       requested_symbols, returned_items, accepted_items, rejected_items,
                       status, failure_reason, raw_response_hash, collector_version,
                       normalizer_version, usage_status, started_at, fetched_at, received_at
                FROM market.research_evidence_batches
                ORDER BY received_at DESC, batch_id DESC
                LIMIT :limit
                OFFSET :offset
                """
            ),
            {"limit": resolved_page_size, "offset": offset},
        )
        items = [serialize_review(dict(row)) for row in result.mappings().all()]
    return ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": resolved_page_size,
            "has_more": offset + len(items) < total,
            "observed_only": True,
            "tradable": False,
            "order_created": False,
            "source": "market.research_evidence_batches",
            "source_version": "research-evidence-observation-v2",
        }
    )


@router.get("/evidence/{evidence_id}")
async def get_research_evidence(evidence_id: UUID):
    async with get_db() as db:
        result = await db.execute(
            text(
                """
                SELECT evidence.evidence_id::text AS evidence_id,
                       evidence.batch_id::text AS batch_id,
                       evidence.evidence_type, evidence.stock_code,
                       evidence.source_document_id, evidence.provider, evidence.source,
                       evidence.publisher_name, evidence.title, evidence.document_url,
                       evidence.source_published_date, evidence.source_published_at,
                       evidence.source_timestamp_raw, evidence.publication_time_precision,
                       evidence.fetched_at, evidence.received_at, evidence.first_observed_at,
                       evidence.available_at, evidence.availability_basis, evidence.raw_hash,
                       evidence.document_bytes, evidence.quality_status, evidence.reject_reason,
                       evidence.fallback_used, evidence.collector_version,
                       evidence.normalizer_version, evidence.usage_status
                FROM market.research_evidence AS evidence
                WHERE evidence.evidence_id = :evidence_id
                """
            ),
            {"evidence_id": evidence_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            error("研究证据不存在", "RESEARCH_EVIDENCE_NOT_FOUND", 404)
        item = serialize_review(dict(row))
        item["financial_report_detail"] = None
        item["financial_report_snapshot_location"] = None
        item["news_detail"] = None
        item["manual_review"] = None

        if item["evidence_type"] == "financial_report":
            detail_result = await db.execute(
                text(
                    """
                    SELECT jsonb_build_object(
                               'provider_category', provider_category,
                               'provider_category_version', provider_category_version,
                               'source_title_raw', source_title_raw,
                               'report_kind', report_kind,
                               'report_period_label', report_period_label,
                               'report_period_end', report_period_end,
                               'period_precision', period_precision,
                               'document_role', document_role,
                               'consolidation_scope', consolidation_scope,
                               'currency_code', currency_code,
                               'currency_unit', currency_unit,
                               'audit_opinion', audit_opinion,
                               'revision_status', revision_status,
                               'supersedes_evidence_id', supersedes_evidence_id,
                               'detail_parse_status', detail_parse_status
                           ) AS detail
                    FROM market.research_financial_report_details
                    WHERE evidence_id = :evidence_id
                    """
                ),
                {"evidence_id": evidence_id},
            )
            detail_row = detail_result.mappings().one_or_none()
            item["financial_report_detail"] = (
                detail_row["detail"] if detail_row is not None else None
            )
            snapshot_result = await db.execute(
                text(
                    """
                    SELECT jsonb_build_object(
                               'snapshot_id', snapshot.snapshot_id,
                               'snapshot_status', snapshot.status,
                               'acquisition_method', snapshot.acquisition_method,
                               'expected_raw_hash', snapshot.expected_raw_hash,
                               'observed_raw_hash', snapshot.observed_raw_hash,
                               'expected_bytes', snapshot.expected_bytes,
                               'observed_bytes', snapshot.observed_bytes,
                               'storage_key', snapshot.storage_key,
                               'source_usage_review_id', snapshot.source_usage_review_id,
                               'parse_run', CASE WHEN parse_run.parse_run_id IS NULL THEN NULL
                                   ELSE jsonb_build_object(
                                       'parse_run_id', parse_run.parse_run_id,
                                       'source_usage_review_id', parse_run.source_usage_review_id,
                                       'parser_name', parse_run.parser_name,
                                       'parser_version', parse_run.parser_version,
                                       'normalization_version', parse_run.normalization_version,
                                       'status', parse_run.status,
                                       'page_count', parse_run.page_count,
                                       'text_page_count', parse_run.text_page_count,
                                       'failure_reason', parse_run.failure_reason,
                                       'locations', COALESCE(location_rows.items, '[]'::jsonb)
                                   ) END
                           ) AS location
                    FROM market.research_financial_report_snapshots AS snapshot
                    LEFT JOIN LATERAL (
                        SELECT run.*
                        FROM market.research_financial_report_parse_runs AS run
                        WHERE run.snapshot_id = snapshot.snapshot_id
                          AND run.status IN ('success', 'partial')
                        ORDER BY run.completed_at DESC, run.parse_run_id DESC
                        LIMIT 1
                    ) AS parse_run ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT jsonb_agg(
                                   jsonb_build_object(
                                       'location_id', location.location_id,
                                       'field_name', location.field_name,
                                       'page_number', page.page_number,
                                       'raw_value', location.raw_value,
                                       'normalized_value', location.normalized_value,
                                       'match_start', location.match_start,
                                       'match_end', location.match_end,
                                       'anchor_hash', location.anchor_hash,
                                       'statement_scope', location.statement_scope,
                                       'status', location.status,
                                       'reason', location.reason,
                                       'locator_version', location.locator_version
                                   )
                                   ORDER BY location.field_name, page.page_number,
                                            location.match_start, location.location_id
                               ) AS items
                        FROM market.research_financial_metadata_locations AS location
                        LEFT JOIN market.research_financial_report_page_evidence AS page
                          ON page.page_evidence_id = location.page_evidence_id
                         AND page.parse_run_id = location.parse_run_id
                        WHERE location.parse_run_id = parse_run.parse_run_id
                    ) AS location_rows ON TRUE
                    WHERE snapshot.evidence_id = :evidence_id
                      AND snapshot.status = 'observed'
                    ORDER BY snapshot.created_at DESC, snapshot.snapshot_id DESC
                    LIMIT 1
                    """
                ),
                {"evidence_id": evidence_id},
            )
            snapshot_row = snapshot_result.mappings().one_or_none()
            item["financial_report_snapshot_location"] = (
                snapshot_row["location"] if snapshot_row is not None else None
            )
        elif item["evidence_type"] == "news":
            detail_result = await db.execute(
                text(
                    """
                    SELECT jsonb_build_object(
                               'provider_feed_url', provider_feed_url,
                               'source_title_raw', source_title_raw,
                               'publisher_domain', publisher_domain,
                               'provider_reported_at', provider_reported_at,
                               'provider_time_semantics', provider_time_semantics,
                               'association_method', association_method,
                               'association_alias', association_alias,
                               'association_status', association_status,
                               'content_scope', content_scope,
                               'feed_window_minutes', feed_window_minutes,
                               'raw_representation', raw_representation,
                               'detail_parse_status', detail_parse_status
                           ) AS detail
                    FROM market.research_news_details
                    WHERE evidence_id = :evidence_id
                    """
                ),
                {"evidence_id": evidence_id},
            )
            detail_row = detail_result.mappings().one_or_none()
            item["news_detail"] = detail_row["detail"] if detail_row is not None else None
            review_result = await db.execute(
                text(
                    """
                    SELECT jsonb_build_object(
                               'review_id', review_id,
                               'reviewer_label', reviewer_label,
                               'conclusion', conclusion,
                               'reason', reason,
                               'reviewed_at', reviewed_at
                           ) AS review
                    FROM market.research_news_evidence_reviews
                    WHERE evidence_id = :evidence_id
                    ORDER BY reviewed_at DESC, review_id DESC
                    LIMIT 1
                    """
                ),
                {"evidence_id": evidence_id},
            )
            review_row = review_result.mappings().one_or_none()
            item["manual_review"] = review_row["review"] if review_row is not None else None

    return ok(
        {
            "item": item,
            "observed_only": True,
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source": "market.research_evidence",
            "source_version": "research-evidence-observation-v2",
        }
    )


@router.get("/evidence/{evidence_id}/financial-location-candidates")
async def list_financial_location_candidates(
    evidence_id: UUID,
    field_name: Literal[
        "report_period_end",
        "statement_currency_unit",
        "audit_opinion_section",
        "statement_scope_heading",
    ]
    | None = Query(None),
    status: Literal["located", "ambiguous", "unresolved", "rejected"] | None = Query(
        None
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    async with get_db() as db:
        evidence = await _find_observed_financial_location_evidence(db, evidence_id)
        if evidence is None:
            error(
                "仅已观察且待复核的财报证据可查询页级定位候选",
                "FINANCIAL_LOCATION_EVIDENCE_NOT_FOUND",
                404,
            )

        parse_run_id = evidence.get("parse_run_id")
        if parse_run_id is None:
            return ok(
                {
                    "evidence": serialize_review(evidence),
                    "items": [],
                    "total": 0,
                    "page": page,
                    "page_size": page_size,
                    "has_more": False,
                    "summary": {
                        "located": 0,
                        "ambiguous": 0,
                        "unresolved": 0,
                        "rejected": 0,
                    },
                    "location_status": "parse_run_unavailable",
                    "observed_only": True,
                    "research_readiness": "not_granted",
                    "tradable": False,
                    "order_created": False,
                    "source": "market.research_financial_metadata_locations",
                    "source_version": "financial-location-candidates-v1",
                }
            )

        filters = ["location.parse_run_id = CAST(:parse_run_id AS uuid)"]
        params: dict[str, Any] = {
            "parse_run_id": parse_run_id,
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        if field_name:
            filters.append("location.field_name = :field_name")
            params["field_name"] = field_name
        if status:
            filters.append("location.status = :status")
            params["status"] = status
        where_clause = " AND ".join(filters)

        summary_result = await db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE location.status = 'located') AS located,
                       COUNT(*) FILTER (WHERE location.status = 'ambiguous') AS ambiguous,
                       COUNT(*) FILTER (WHERE location.status = 'unresolved') AS unresolved,
                       COUNT(*) FILTER (WHERE location.status = 'rejected') AS rejected
                FROM market.research_financial_metadata_locations AS location
                WHERE {where_clause}
                """
            ),
            params,
        )
        summary = dict(summary_result.mappings().one())
        result = await db.execute(
            text(
                f"""
                SELECT location.location_id::text AS location_id,
                       location.parse_run_id::text AS parse_run_id,
                       location.page_evidence_id::text AS page_evidence_id,
                       location.field_name, location.raw_value, location.normalized_value,
                       location.match_start, location.match_end, location.anchor_hash,
                       location.statement_scope, location.status, location.reason,
                       location.locator_version, location.created_at,
                       page.page_number, page.extraction_status,
                       page.text_hash, page.character_count, page.failure_reason
                FROM market.research_financial_metadata_locations AS location
                LEFT JOIN market.research_financial_report_page_evidence AS page
                  ON page.page_evidence_id = location.page_evidence_id
                 AND page.parse_run_id = location.parse_run_id
                WHERE {where_clause}
                ORDER BY location.field_name, page.page_number NULLS LAST,
                         location.match_start NULLS LAST, location.location_id
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [serialize_review(dict(row)) for row in result.mappings().all()]

    return ok(
        {
            "evidence": serialize_review(evidence),
            "items": items,
            "total": int(summary["total"] or 0),
            "page": page,
            "page_size": page_size,
            "has_more": (page - 1) * page_size + len(items)
            < int(summary["total"] or 0),
            "summary": {
                "located": int(summary["located"] or 0),
                "ambiguous": int(summary["ambiguous"] or 0),
                "unresolved": int(summary["unresolved"] or 0),
                "rejected": int(summary["rejected"] or 0),
            },
            "location_status": "available",
            "observed_only": True,
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source": "market.research_financial_metadata_locations",
            "source_version": "financial-location-candidates-v1",
        }
    )


@router.get("/evidence/{evidence_id}/financial-location-reviews")
async def list_financial_location_reviews(
    evidence_id: UUID,
    location_id: UUID | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    async with get_db() as db:
        evidence = await _find_observed_financial_location_evidence(db, evidence_id)
        if evidence is None:
            error(
                "仅已观察且待复核的财报证据可查询页级定位复核历史",
                "FINANCIAL_LOCATION_EVIDENCE_NOT_FOUND",
                404,
            )

        filters = ["review.evidence_id = :evidence_id"]
        params: dict[str, Any] = {
            "evidence_id": evidence_id,
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        if location_id:
            filters.append("review.location_id = :location_id")
            params["location_id"] = location_id
        where_clause = " AND ".join(filters)

        total_result = await db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total
                FROM market.research_financial_metadata_location_reviews AS review
                WHERE {where_clause}
                """
            ),
            params,
        )
        total = int(total_result.mappings().one()["total"] or 0)
        result = await db.execute(
            text(
                f"""
                SELECT review.review_id::text AS review_id,
                       review.evidence_id::text AS evidence_id,
                       review.location_id::text AS location_id,
                       review.snapshot_id::text AS snapshot_id,
                       review.parse_run_id::text AS parse_run_id,
                       review.page_evidence_id::text AS page_evidence_id,
                       review.raw_hash, review.locator_version,
                       review.reviewer_label,
                       review.reviewer_principal_id::text AS reviewer_principal_id,
                       review.conclusion, review.reason, review.reviewed_at,
                       location.field_name, location.status AS location_status,
                       page.page_number
                FROM market.research_financial_metadata_location_reviews AS review
                INNER JOIN market.research_financial_metadata_locations AS location
                  ON location.location_id = review.location_id
                INNER JOIN market.research_financial_report_page_evidence AS page
                  ON page.parse_run_id = review.parse_run_id
                 AND page.page_evidence_id = review.page_evidence_id
                WHERE {where_clause}
                ORDER BY review.reviewed_at DESC, review.review_id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [serialize_review(dict(row)) for row in result.mappings().all()]

    return ok(
        {
            "evidence": serialize_review(evidence),
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": (page - 1) * page_size + len(items) < total,
            "review_scope": "financial_location_only",
            "observed_only": True,
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source": "market.research_financial_metadata_location_reviews",
            "source_version": "financial-location-review-v1",
        }
    )


@router.get("/evidence/{evidence_id}/reviews")
async def list_news_evidence_manual_reviews(evidence_id: UUID):
    async with get_db() as db:
        evidence = await _find_reviewable_news_evidence(db, evidence_id)
        if evidence is None:
            error("仅已观察且待复核的新闻证据可查询人工复核", "NEWS_REVIEW_NOT_FOUND", 404)
        result = await db.execute(
            text(
                """
                SELECT review_id::text AS review_id, evidence_id::text AS evidence_id,
                       reviewer_label, reviewer_principal_id::text AS reviewer_principal_id,
                       conclusion, reason, reviewed_at
                FROM market.research_news_evidence_reviews
                WHERE evidence_id = :evidence_id
                ORDER BY reviewed_at DESC, review_id DESC
                """
            ),
            {"evidence_id": evidence_id},
        )
        items = [serialize_review(dict(row)) for row in result.mappings().all()]
    return ok(
        {
            "evidence": serialize_review(evidence),
            "items": items,
            "total": len(items),
            "review_scope": "title_link_only",
            "observed_only": True,
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source": "market.research_news_evidence_reviews",
            "source_version": "research-news-manual-review-v1",
        }
    )


@router.post("/evidence/{evidence_id}/reviews")
async def append_news_evidence_manual_review(
    evidence_id: UUID, body: NewsEvidenceManualReviewRequest, request: Request
):
    reason = body.reason.strip()
    principal = get_request_principal(request)
    idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
    if not 8 <= len(idempotency_key) <= 128:
        error("缺少有效的 Idempotency-Key", "IDEMPOTENCY_KEY_REQUIRED", 422)
    request_hash = _news_review_request_hash(evidence_id, body)
    if not reason:
        error("复核人标识和复核理由不能为空", "INVALID_NEWS_REVIEW", 422)

    async with get_db() as db:
        evidence = await _find_reviewable_news_evidence(db, evidence_id)
        if evidence is None:
            error("仅已观察且待复核的新闻证据可追加人工复核", "NEWS_REVIEW_NOT_FOUND", 404)
        result = await db.execute(
            text(
                """
                INSERT INTO market.research_news_evidence_reviews (
                    review_id, evidence_id, reviewer_label, reviewer_principal_id,
                    idempotency_key, request_hash, conclusion, reason
                ) VALUES (
                    :review_id, :evidence_id, :reviewer_label, CAST(:reviewer_principal_id AS uuid),
                    :idempotency_key, :request_hash, :conclusion, :reason
                )
                ON CONFLICT (reviewer_principal_id, idempotency_key)
                    WHERE reviewer_principal_id IS NOT NULL
                DO NOTHING
                RETURNING review_id::text AS review_id, evidence_id::text AS evidence_id,
                          reviewer_label, reviewer_principal_id::text AS reviewer_principal_id,
                          idempotency_key, request_hash, conclusion, reason, reviewed_at
                """
            ),
            {
                "review_id": uuid4(),
                "evidence_id": evidence_id,
                "reviewer_label": principal.display_name,
                "reviewer_principal_id": principal.principal_id,
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
                "conclusion": body.conclusion,
                "reason": reason,
            },
        )
        row = result.mappings().first()
        if row is None:
            existing = await db.execute(
                text(
                    """
                    SELECT review_id::text AS review_id, evidence_id::text AS evidence_id,
                           reviewer_label, reviewer_principal_id::text AS reviewer_principal_id,
                           idempotency_key, request_hash, conclusion, reason, reviewed_at
                    FROM market.research_news_evidence_reviews
                    WHERE reviewer_principal_id = CAST(:reviewer_principal_id AS uuid)
                      AND idempotency_key = :idempotency_key
                    """
                ),
                {
                    "reviewer_principal_id": principal.principal_id,
                    "idempotency_key": idempotency_key,
                },
            )
            row = existing.mappings().one()
            if row["request_hash"] != request_hash:
                error("同一 Idempotency-Key 不能绑定不同复核请求", "IDEMPOTENCY_KEY_PAYLOAD_CONFLICT", 409)
        review = serialize_review(dict(row))
    return ok(
        {
            "evidence": serialize_review(evidence),
            "item": review,
            "review_scope": "title_link_only",
            "observed_only": True,
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source": "market.research_news_evidence_reviews",
            "source_version": "research-news-manual-review-v1",
        },
        message="新闻标题链接人工复核已追加",
    )


@router.get("/candidate-status")
async def get_research_candidate_status(limit: int = Query(5, ge=1, le=50)):
    """只读展示研究资格排除项；不运行 Screener，也不发布候选。"""
    async with get_db() as db:
        result = await db.execute(
            text(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (stock_code)
                           review_id, stock_code, date_from, date_to,
                           readiness_status, research_use_scope,
                           requirement_profile, review_reason, reviewed_at
                    FROM market.research_readiness_reviews
                    WHERE research_use_scope = 'return_backtest'
                    ORDER BY stock_code, reviewed_at DESC, review_id DESC
                )
                SELECT * FROM latest
                WHERE readiness_status <> 'ready'
                ORDER BY reviewed_at DESC, stock_code
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        items = [serialize_review(dict(row)) for row in result.mappings().all()]
        status_result = await db.execute(
            text(
                """
                SELECT readiness_status, COUNT(*) AS count
                FROM (
                    SELECT DISTINCT ON (stock_code)
                           stock_code, readiness_status, reviewed_at, review_id
                    FROM market.research_readiness_reviews
                    WHERE research_use_scope = 'return_backtest'
                    ORDER BY stock_code, reviewed_at DESC, review_id DESC
                ) latest
                GROUP BY readiness_status
                """
            )
        )
        counts = {
            str(row["readiness_status"]): int(row["count"] or 0)
            for row in status_result.mappings().all()
        }

    published = bool(settings.CERTIFIED_SCREENER_OUTPUT_ENABLED)
    snapshot_hash = _research_candidate_snapshot_hash(items, counts, published)
    return ok(
        {
            "items": items,
            "counts": counts,
            "snapshot_hash": snapshot_hash,
            "candidate_count": None if published else 0,
            "candidate_status": "published" if published else "release_locked",
            "tradable": False,
            "order_created": False,
            "release_lock": {
                "key": "CERTIFIED_SCREENER_OUTPUT_ENABLED",
                "enabled": published,
                "reason": (
                    "已由当前环境显式开启"
                    if published
                    else "真实选股输出关闭；当前仅展示资格排除项"
                ),
            },
            "source": "market.research_readiness_reviews",
            "source_version": "research-candidate-status-v1",
        }
    )
