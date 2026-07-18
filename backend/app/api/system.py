from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from sqlalchemy import text

from app.api.trade import build_execution_status
from app.core.response import ok
from app.db import get_db

router = APIRouter()


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
