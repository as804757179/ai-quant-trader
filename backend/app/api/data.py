from datetime import date
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import text

from app.core.response import ok
from app.data.certified_kline_repository import CertifiedKlineRepository
from app.db import get_db


router = APIRouter()


@router.get("/certified-klines")
async def list_certified_klines(
    stock_code: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    period: str = Query("1d", min_length=1, max_length=10),
    adjustment: str = Query("raw", pattern="^(raw|qfq|hfq)$"),
    batch_id: str | None = Query(None, min_length=1, max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    data = await CertifiedKlineRepository().list_lineage(
        stock_code=stock_code,
        date_from=date_from,
        date_to=date_to,
        period=period,
        adjustment=adjustment,
        batch_id=batch_id,
        page=page,
        page_size=page_size,
    )
    data.update(
        {
            "certification_scope": "certified_store_observation",
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source": "market.certified_klines",
            "source_version": "certified-kline-lineage-v1",
        }
    )
    return ok(data)


@router.get("/certification-batches")
async def list_certification_batches(
    provider: str | None = Query(None, min_length=1, max_length=64),
    source: str | None = Query(None, min_length=1, max_length=64),
    period: str | None = Query(None, min_length=1, max_length=10),
    stock_code: str | None = Query(None, min_length=1, max_length=12),
    status: str | None = Query(None, min_length=1, max_length=20),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    filters = ["1=1"]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    if provider:
        filters.append("batch.provider = :provider")
        params["provider"] = provider.strip()
    if source:
        filters.append("batch.source = :source")
        params["source"] = source.strip()
    if period:
        filters.append("batch.period = :period")
        params["period"] = period.strip()
    if stock_code:
        filters.append("batch.stock_code = :stock_code")
        params["stock_code"] = stock_code.strip().upper()
    if status:
        filters.append("batch.status = :status")
        params["status"] = status.strip()
    if date_from:
        filters.append("batch.end_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        filters.append("batch.start_date <= :date_to")
        params["date_to"] = date_to
    where_clause = " AND ".join(filters)
    async with get_db() as db:
        summary_result = await db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE batch.status = 'certified') AS certified,
                       COUNT(*) FILTER (WHERE batch.status = 'rejected') AS rejected,
                       COUNT(*) FILTER (WHERE batch.status IN ('failed', 'fetch_failed', 'validation_failed', 'write_failed')) AS failed,
                       MAX(batch.fetch_time) AS latest_fetch_time
                FROM market.data_batches AS batch
                WHERE {where_clause}
                """
            ),
            params,
        )
        summary = dict(summary_result.mappings().one())
        result = await db.execute(
            text(
                f"""
                SELECT batch.batch_id, batch.stock_code, batch.provider, batch.source,
                       batch.period, batch.start_date, batch.end_date, batch.fetch_time,
                       batch.importer_version, batch.total_rows, batch.accepted_rows,
                       batch.rejected_rows, batch.quality_score, batch.status,
                       batch.reject_reason, batch.provider_priority, batch.fallback_used,
                       batch.fetch_endpoint, batch.raw_hash, batch.created_at
                FROM market.data_batches AS batch
                WHERE {where_clause}
                ORDER BY batch.fetch_time DESC, batch.batch_id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [dict(row) for row in result.mappings().all()]
    total = int(summary["total"] or 0)
    return ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": (page - 1) * page_size + len(items) < total,
            "summary": {
                "certified": int(summary["certified"] or 0),
                "rejected": int(summary["rejected"] or 0),
                "failed": int(summary["failed"] or 0),
                "latest_fetch_time": summary["latest_fetch_time"],
            },
            "certification_scope": "batch_observation",
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source": "market.data_batches",
            "source_version": "certification-batches-v1",
        }
    )


@router.get("/quality-results")
async def list_quality_results(
    batch_id: str | None = Query(None, min_length=1, max_length=64),
    stock_code: str | None = Query(None, min_length=1, max_length=12),
    rule_code: str | None = Query(None, min_length=1, max_length=64),
    result: str | None = Query(None, pattern="^(pass|fail|not_evaluated)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    filters = ["1=1"]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    if batch_id:
        filters.append("quality.batch_id = :batch_id")
        params["batch_id"] = batch_id.strip()
    if stock_code:
        filters.append("batch.stock_code = :stock_code")
        params["stock_code"] = stock_code.strip().upper()
    if rule_code:
        filters.append("quality.rule_code = :rule_code")
        params["rule_code"] = rule_code.strip()
    if result:
        filters.append("quality.result = :result")
        params["result"] = result
    where_clause = " AND ".join(filters)
    async with get_db() as db:
        summary_result = await db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE quality.result = 'pass') AS passed,
                       COUNT(*) FILTER (WHERE quality.result = 'fail') AS failed,
                       COUNT(*) FILTER (WHERE quality.result = 'not_evaluated') AS not_evaluated,
                       MAX(quality.created_at) AS latest_evaluated_at
                FROM market.data_quality_results AS quality
                INNER JOIN market.data_batches AS batch ON batch.batch_id = quality.batch_id
                WHERE {where_clause}
                """
            ),
            params,
        )
        summary = dict(summary_result.mappings().one())
        rows = await db.execute(
            text(
                f"""
                SELECT quality.quality_result_id, quality.batch_id, quality.rule_code,
                       quality.rule_version, quality.audit_scope, quality.result,
                       quality.reject_reason, quality.input_hash, quality.created_at,
                       batch.stock_code, batch.provider, batch.source, batch.period,
                       batch.fetch_time, batch.importer_version
                FROM market.data_quality_results AS quality
                INNER JOIN market.data_batches AS batch ON batch.batch_id = quality.batch_id
                WHERE {where_clause}
                ORDER BY quality.created_at DESC, quality.quality_result_id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [dict(row) for row in rows.mappings().all()]
    total = int(summary["total"] or 0)
    return ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": (page - 1) * page_size + len(items) < total,
            "summary": {
                "passed": int(summary["passed"] or 0),
                "failed": int(summary["failed"] or 0),
                "not_evaluated": int(summary["not_evaluated"] or 0),
                "latest_evaluated_at": summary["latest_evaluated_at"],
            },
            "certification_scope": "quality_observation",
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source": "market.data_quality_results",
            "source_version": "quality-results-v1",
        }
    )


@router.get("/blockers")
async def list_data_blockers(
    stock_code: str | None = Query(None, min_length=1, max_length=12),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    classification: str | None = Query(
        None,
        pattern="^(non_trading_day|suspended|security_ineligible|provider_missing|corporate_action_unresolved|unresolved)$",
    ),
    status: str | None = Query(None, min_length=1, max_length=40),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    filters = ["1=1"]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    if stock_code:
        filters.append("blocker.stock_code = :stock_code")
        params["stock_code"] = stock_code.strip().upper()
    if date_from:
        filters.append("blocker.trading_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        filters.append("blocker.trading_date <= :date_to")
        params["date_to"] = date_to
    if classification:
        filters.append("blocker.classification = :classification")
        params["classification"] = classification
    if status:
        filters.append("blocker.status = :status")
        params["status"] = status.strip()
    where_clause = " AND ".join(filters)
    source_rows = """
        SELECT review.date_review_id AS blocker_id, review.dataset_scope, review.stock_code,
               review.trading_date,
               CASE review.status
                    WHEN 'exchange_closed' THEN 'non_trading_day'
                    WHEN 'suspended' THEN 'suspended'
                    WHEN 'not_listed' THEN 'security_ineligible'
                    WHEN 'delisted' THEN 'security_ineligible'
                    WHEN 'provider_missing' THEN 'provider_missing'
                    ELSE 'unresolved'
               END AS classification,
               review.status, review.evidence_source, review.reviewer_version AS evidence_version,
               review.evidence_time, review.reviewed_at, review.reason
        FROM market.research_date_reviews AS review
        WHERE review.status <> 'normal_trade'
        UNION ALL
        SELECT 'security-status:' || review.run_id || ':' || review.stock_code || ':' || review.effective_from || ':' || review.status,
               review.run_id, review.stock_code, review.effective_from,
               CASE review.status
                    WHEN 'exchange_closed' THEN 'non_trading_day'
                    WHEN 'suspended' THEN 'suspended'
                    WHEN 'not_listed' THEN 'security_ineligible'
                    WHEN 'delisted' THEN 'security_ineligible'
                    WHEN 'provider_missing' THEN 'provider_missing'
                    ELSE 'unresolved'
               END,
               review.status, review.evidence_source, review.evidence_version,
               review.reviewed_at, review.reviewed_at, NULL
        FROM market.security_status_reviews AS review
        WHERE review.status IN ('exchange_closed', 'suspended', 'not_listed', 'delisted', 'provider_missing', 'unresolved')
        UNION ALL
        SELECT 'corporate-action:' || review.event_id, 'corporate_action_review', review.stock_code,
               COALESCE(review.effective_date, review.ex_date, review.record_date, review.announcement_date),
               'corporate_action_unresolved', review.verification_status, review.source,
               review.reviewer_version, review.reviewed_at, review.reviewed_at,
               COALESCE(review.evidence->>'finding', 'corporate action review is unresolved')
        FROM market.corporate_action_reviews AS review
        WHERE review.verification_status = 'unresolved'
    """
    async with get_db() as db:
        summary_result = await db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE blocker.classification = 'unresolved') AS unresolved,
                       COUNT(*) FILTER (WHERE blocker.classification = 'provider_missing') AS provider_missing,
                       MAX(blocker.reviewed_at) AS latest_reviewed_at
                FROM ({source_rows}) AS blocker
                WHERE {where_clause}
                """
            ),
            params,
        )
        summary = dict(summary_result.mappings().one())
        result = await db.execute(
            text(
                f"""
                SELECT blocker.*, NULL::BOOLEAN AS readiness_blocking,
                       'not_recorded' AS readiness_linkage_status
                FROM ({source_rows}) AS blocker
                WHERE {where_clause}
                ORDER BY blocker.trading_date DESC NULLS LAST, blocker.blocker_id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [dict(row) for row in result.mappings().all()]
    total = int(summary["total"] or 0)
    return ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": (page - 1) * page_size + len(items) < total,
            "summary": {
                "unresolved": int(summary["unresolved"] or 0),
                "provider_missing": int(summary["provider_missing"] or 0),
                "latest_reviewed_at": summary["latest_reviewed_at"],
            },
            "research_readiness": "not_granted",
            "readiness_linkage": "not_recorded",
            "tradable": False,
            "order_created": False,
            "source": "market.research_date_reviews,market.security_status_reviews,market.corporate_action_reviews",
            "source_version": "data-blockers-v1",
        }
    )


@router.get("/provider-validations")
async def list_provider_validations(
    stock_code: str | None = Query(None, min_length=1, max_length=12),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    field: str | None = Query(None, min_length=1, max_length=64),
    conclusion: str | None = Query(None, pattern="^(PASS|REVIEW|FAIL)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    filters = ["1=1"]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    if stock_code:
        filters.append("validation.stock_code = :stock_code")
        params["stock_code"] = stock_code.strip().upper()
    if date_from:
        filters.append("validation.trading_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        filters.append("validation.trading_date <= :date_to")
        params["date_to"] = date_to
    if field:
        filters.append("validation.field = :field")
        params["field"] = field.strip()
    if conclusion:
        filters.append("validation.conclusion = :conclusion")
        params["conclusion"] = conclusion
    where_clause = " AND ".join(filters)
    source_rows = """
        SELECT review.run_id, review.stock_code, review.trading_date,
               review.primary_provider, review.secondary_provider, review.result AS conclusion,
               field.key AS field, field.value->>'primary' AS primary_value,
               field.value->>'secondary' AS secondary_value,
               field.value->>'absolute_difference' AS absolute_difference,
               field.value->>'relative_difference' AS relative_difference,
               field.value->>'tolerance' AS tolerance, field.value->>'passed' AS field_passed,
               review.endpoint_versions, review.comparison, review.reviewed_at
        FROM market.provider_validation_reviews AS review
        CROSS JOIN LATERAL jsonb_each(COALESCE(review.comparison->'fields', '{}'::jsonb)) AS field
        UNION ALL
        SELECT review.run_id, review.stock_code, review.trading_date,
               review.primary_provider, review.secondary_provider, review.result,
               'provider_fetch', NULL, NULL, NULL, NULL, NULL, NULL,
               review.endpoint_versions, review.comparison, review.reviewed_at
        FROM market.provider_validation_reviews AS review
        WHERE review.comparison ? 'provider_fetch_error'
    """
    async with get_db() as db:
        summary_result = await db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE validation.conclusion = 'PASS') AS passed,
                       COUNT(*) FILTER (WHERE validation.conclusion = 'REVIEW') AS review,
                       COUNT(*) FILTER (WHERE validation.conclusion = 'FAIL') AS failed,
                       MAX(validation.reviewed_at) AS latest_reviewed_at
                FROM ({source_rows}) AS validation
                WHERE {where_clause}
                """
            ),
            params,
        )
        summary = dict(summary_result.mappings().one())
        result = await db.execute(
            text(
                f"""
                SELECT * FROM ({source_rows}) AS validation
                WHERE {where_clause}
                ORDER BY validation.trading_date DESC, validation.stock_code, validation.field
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [dict(row) for row in result.mappings().all()]
    total = int(summary["total"] or 0)
    return ok({
        "items": items, "total": total, "page": page, "page_size": page_size,
        "has_more": (page - 1) * page_size + len(items) < total,
        "summary": {"passed": int(summary["passed"] or 0), "review": int(summary["review"] or 0), "failed": int(summary["failed"] or 0), "latest_reviewed_at": summary["latest_reviewed_at"]},
        "research_readiness": "not_granted", "tradable": False, "order_created": False,
        "source": "market.provider_validation_reviews", "source_version": "provider-validations-v1",
    })
