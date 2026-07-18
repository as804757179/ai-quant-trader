from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from sqlalchemy import text

from app.api.trade import build_execution_status
from app.core.response import ok
from app.db import get_db

router = APIRouter()


_DATA_BLOCKER_ROWS = """
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


@router.get("/alerts")
async def list_system_alerts(
    category: str | None = Query(None, pattern="^(system_operation|data_qualification)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """只读汇总系统运行与数据资格记录，不读取风险事件。"""
    filters = ["1=1"]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    if category:
        filters.append("alert.category = :category")
        params["category"] = category
    where_clause = " AND ".join(filters)
    alerts_cte = f"""
        WITH alerts AS (
            SELECT 'system_operation' AS category,
                   'operation-job:' || job.job_id::text AS alert_id,
                   CASE WHEN job.status = 'failed' THEN 'error' ELSE 'warning' END AS severity,
                   'operation_job_' || job.status AS alert_type,
                   job.job_type AS owner,
                   COALESCE(job.finished_at, job.updated_at, job.created_at) AS event_time,
                   job.job_id::text AS related_id,
                   job.error_code AS detail_code,
                   'audit.async_jobs' AS source,
                   'operation-job-audit-v1' AS source_version
            FROM audit.async_jobs AS job
            WHERE job.status IN ('failed', 'blocked')
            UNION ALL
            SELECT 'data_qualification',
                   'data-blocker:' || blocker.blocker_id,
                   CASE WHEN blocker.classification IN ('unresolved', 'provider_missing', 'corporate_action_unresolved')
                        THEN 'warning' ELSE 'info' END,
                   'data_blocker:' || blocker.classification,
                   blocker.dataset_scope,
                   blocker.reviewed_at,
                   blocker.blocker_id,
                   blocker.status,
                   'market.data_blocker_reviews',
                   'data-blockers-v1'
            FROM ({_DATA_BLOCKER_ROWS}) AS blocker
        )
    """
    async with get_db() as db:
        summary_result = await db.execute(
            text(
                f"""
                {alerts_cte}
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE category = 'system_operation') AS system_operation,
                       COUNT(*) FILTER (WHERE category = 'data_qualification') AS data_qualification,
                       MAX(event_time) AS latest_event_at
                FROM alerts AS alert
                WHERE {where_clause}
                """
            ),
            params,
        )
        summary = dict(summary_result.mappings().one())
        result = await db.execute(
            text(
                f"""
                {alerts_cte}
                SELECT * FROM alerts AS alert
                WHERE {where_clause}
                ORDER BY event_time DESC NULLS LAST, alert_id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [dict(row) for row in result.mappings().all()]
    execution_status = build_execution_status()
    total = int(summary["total"] or 0)
    return ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": params["offset"] + len(items) < total,
            "summary": {
                "system_operation": int(summary["system_operation"] or 0),
                "data_qualification": int(summary["data_qualification"] or 0),
                "latest_event_at": (
                    summary["latest_event_at"].isoformat()
                    if summary["latest_event_at"]
                    else None
                ),
            },
            "business_release": {
                "status": "not_granted",
                "release_locks": execution_status["release_locks"],
                "all_release_locks_closed": execution_status["all_release_locks_closed"],
            },
            "risk_alerts_included": False,
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source": "audit.async_jobs + data blocker review records",
            "source_version": "system-alerts-v1",
        }
    )


@router.get("/jobs")
async def list_system_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """只读返回已审计的异步任务，不调度、停止或重试任务。"""
    params = {"limit": page_size, "offset": (page - 1) * page_size}
    async with get_db() as db:
        summary_result = await db.execute(
            text(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status IN ('queued', 'retry_wait', 'cancel_requested')) AS pending,
                       COUNT(*) FILTER (WHERE status = 'running') AS running,
                       COUNT(*) FILTER (WHERE status IN ('failed', 'blocked')) AS failed_or_blocked,
                       MAX(updated_at) AS latest_updated_at
                FROM audit.async_jobs
                """
            )
        )
        summary = dict(summary_result.mappings().one())
        result = await db.execute(
            text(
                """
                SELECT job_id::text, job_type, status, progress, error_code,
                       retry_count, max_retries, next_retry_at, created_at, started_at,
                       finished_at, updated_at, last_stage, operation_approval_id::text
                FROM audit.async_jobs
                ORDER BY updated_at DESC, job_id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [dict(row) for row in result.mappings().all()]

    execution_status = build_execution_status()
    total = int(summary["total"] or 0)
    return ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": params["offset"] + len(items) < total,
            "summary": {
                "pending": int(summary["pending"] or 0),
                "running": int(summary["running"] or 0),
                "failed_or_blocked": int(summary["failed_or_blocked"] or 0),
                "latest_updated_at": (
                    summary["latest_updated_at"].isoformat()
                    if summary["latest_updated_at"]
                    else None
                ),
            },
            "scheduler": {
                "registration_status": "not_observed",
                "registration_source": "worker.celery_app.beat_schedule",
                "runtime_status": "not_observed",
                "timezone": "Asia/Shanghai",
            },
            "business_release": {
                "status": "not_granted",
                "all_release_locks_closed": execution_status["all_release_locks_closed"],
                "release_locks": execution_status["release_locks"],
            },
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source": "audit.async_jobs + scheduler declaration metadata",
            "source_version": "system-jobs-v1",
        }
    )


@router.get("/audit-events")
async def list_system_audit_events(
    event_type: str | None = Query(None, max_length=100),
    related_id: str | None = Query(None, max_length=100),
    subject: str | None = Query(None, max_length=50),
    from_time: datetime | None = Query(None),
    to_time: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """只读查询平台操作审计事件，不返回审计载荷或提供变更入口。"""
    filters = ["1=1"]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    for value, column, parameter in (
        (event_type, "event.operation", "event_type"),
        (related_id, "event.entity_id", "related_id"),
        (subject, "event.operator", "subject"),
    ):
        if value:
            filters.append(f"{column} = :{parameter}")
            params[parameter] = value
    if from_time:
        filters.append("event.created_at >= :from_time")
        params["from_time"] = from_time
    if to_time:
        filters.append("event.created_at <= :to_time")
        params["to_time"] = to_time
    where_clause = " AND ".join(filters)
    async with get_db() as db:
        summary_result = await db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(DISTINCT event.operation) AS event_types,
                       COUNT(*) FILTER (WHERE event.result = 'SUCCESS') AS successful,
                       MAX(event.created_at) AS latest_created_at
                FROM audit.operation_logs AS event
                WHERE {where_clause}
                """
            ),
            params,
        )
        summary = dict(summary_result.mappings().one())
        result = await db.execute(
            text(
                f"""
                SELECT event.id::text AS event_id, event.operation AS event_type,
                       event.entity_type, event.entity_id AS related_id,
                       event.operator AS subject, event.result, event.created_at,
                       event.before_data IS NOT NULL AS before_recorded,
                       event.after_data IS NOT NULL AS after_recorded
                FROM audit.operation_logs AS event
                WHERE {where_clause}
                ORDER BY event.created_at DESC NULLS LAST, event.id DESC
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
            "has_more": params["offset"] + len(items) < total,
            "summary": {
                "event_types": int(summary["event_types"] or 0),
                "successful": int(summary["successful"] or 0),
                "latest_created_at": (
                    summary["latest_created_at"].isoformat()
                    if summary["latest_created_at"]
                    else None
                ),
            },
            "integrity": {
                "event_hash_observed": False,
                "event_hash_status": "not_recorded",
            },
            "research_readiness": "not_granted",
            "tradable": False,
            "order_created": False,
            "source": "audit.operation_logs",
            "source_version": "system-audit-events-v1",
        }
    )


@router.get("/health")
async def get_system_health():
    """只读汇总当前请求可观察到的基础设施、数据资格和发布锁状态。"""
    observed_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    database_status = "available"
    readiness_summary: dict[str, Any] | None = None
    try:
        async with get_db() as db:
            await db.execute(text("SELECT 1"))
            result = await db.execute(
                text(
                    """
                    SELECT COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE readiness_status = 'ready') AS ready,
                           COUNT(*) FILTER (WHERE readiness_status = 'review_required') AS review_required,
                           COUNT(*) FILTER (WHERE readiness_status = 'rejected') AS rejected,
                           MAX(reviewed_at) AS latest_reviewed_at
                    FROM market.research_readiness_reviews
                    """
                )
            )
            readiness_summary = dict(result.mappings().one())
    except Exception:
        database_status = "unavailable"

    if readiness_summary is None:
        data_qualification = {
            "status": "unavailable",
            "summary": None,
            "research_readiness": "not_granted",
        }
    else:
        total = int(readiness_summary["total"] or 0)
        data_qualification = {
            "status": "not_evaluated" if total == 0 else "records_observed",
            "summary": {
                "total": total,
                "ready": int(readiness_summary["ready"] or 0),
                "review_required": int(readiness_summary["review_required"] or 0),
                "rejected": int(readiness_summary["rejected"] or 0),
                "latest_reviewed_at": (
                    readiness_summary["latest_reviewed_at"].isoformat()
                    if readiness_summary["latest_reviewed_at"]
                    else None
                ),
            },
            "research_readiness": "not_granted",
        }

    execution_status = build_execution_status()
    return ok(
        {
            "infrastructure": {
                "status": "observed" if database_status == "available" else "partial_observed",
                "components": [
                    {
                        "component": "api",
                        "status": "observed",
                        "detail": "本次只读健康请求已由 API 进程响应",
                        "observed_at": observed_at,
                    },
                    {
                        "component": "database",
                        "status": database_status,
                        "detail": "仅执行 SELECT 1 连通性检查",
                        "observed_at": observed_at,
                    },
                ],
            },
            "data_qualification": data_qualification,
            "business_release": {
                "status": "not_granted",
                "all_release_locks_closed": execution_status["all_release_locks_closed"],
                "release_locks": execution_status["release_locks"],
                "tradable": False,
                "order_created": False,
            },
            "observed_only": True,
            "source": "runtime api/database probe + market.research_readiness_reviews + execution safety settings",
            "source_version": "system-health-v1",
        }
    )
