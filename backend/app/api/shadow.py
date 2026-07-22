from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy.exc import SQLAlchemyError

from app.core.response import error, ok
from app.db import get_db
from app.shadow.repository import ShadowRepository


router = APIRouter()
_repository = ShadowRepository()


def _database_context():
    return get_db()


def _database_error(exc: SQLAlchemyError) -> None:
    error("P3-0 影子审计存储不可用", "P3_SHADOW_UNAVAILABLE", 503, retryable=True)


@router.get("/runs")
async def list_shadow_runs(
    status: str | None = Query(None, pattern="^(created|running|blocked|succeeded|failed)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    try:
        async with _database_context() as db:
            items, total = await _repository.list_runs(
                db, status=status, page=page, page_size=page_size
            )
    except SQLAlchemyError as exc:
        _database_error(exc)
    return ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "data_mode_semantics": "test/replay/realtime are not interchangeable",
        }
    )


@router.get("/runs/{run_id}")
async def get_shadow_run(run_id: UUID):
    try:
        async with _database_context() as db:
            item = await _repository.get_run(db, run_id=run_id)
    except SQLAlchemyError as exc:
        _database_error(exc)
    if not item:
        error("影子运行不存在", "P3_SHADOW_RUN_NOT_FOUND", 404)
    return ok(item)


@router.get("/runs/{run_id}/decisions")
async def list_shadow_decisions(
    run_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    try:
        async with _database_context() as db:
            items, total = await _repository.list_decisions(
                db, run_id=run_id, page=page, page_size=page_size
            )
    except SQLAlchemyError as exc:
        _database_error(exc)
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/decisions/{decision_id}/evidence")
async def list_shadow_decision_evidence(decision_id: UUID):
    try:
        async with _database_context() as db:
            items = await _repository.list_decision_evidence(db, decision_id=decision_id)
    except SQLAlchemyError as exc:
        _database_error(exc)
    return ok({"items": items, "total": len(items)})
