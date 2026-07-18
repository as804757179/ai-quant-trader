"""Persisted execution for legacy long-running operation endpoints."""

from __future__ import annotations

import importlib.util
import traceback
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.auth import Principal
from app.data.kline_backfill import KlineBackfillService, estimate_limit_for_range
from app.db import get_db
from app.jobs.dispatch import OperationJobDispatchError, dispatch_operation_job
from app.jobs.service import AsyncJobError, AsyncJobStore
from app.trade.execution_authorization import (
    ExecutionAuthorizationError,
    ExecutionAuthorizationService,
)


OPERATION_JOB_TYPES = frozenset(
    {
        "market.sync_universe",
        "market.backfill_kline",
        "ai.analyze",
        "trade.orders_sync",
        "trade.reconcile",
    }
)
_OPERATION_LEASE_SECONDS = 660


class OperationJobInputError(AsyncJobError):
    code = "OPERATION_JOB_INPUT_INVALID"
    status_code = 422


class OperationJobWorkerForbidden(AsyncJobError):
    code = "OPERATION_JOB_WORKER_FORBIDDEN"
    status_code = 403


class OperationJobApprovalError(OperationJobInputError):
    code = "OPERATION_JOB_APPROVAL_INVALID"
    status_code = 403

    def __init__(
        self,
        message: str,
        *,
        code: str = "OPERATION_JOB_APPROVAL_INVALID",
        status_code: int = 403,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class OperationJobUnsupported(AsyncJobError):
    code = "OPERATION_JOB_UNSUPPORTED"
    status_code = 409


class OperationJobPermanentFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class OperationJobService:
    """Create and execute legacy operation Jobs without inline HTTP work."""

    def __init__(self, *, store: AsyncJobStore | None = None) -> None:
        self.store = store or AsyncJobStore()

    async def submit(
        self,
        *,
        job_type: str,
        principal: Principal,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        job, created = await self.create(
            job_type=job_type,
            principal=principal,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if created:
            job = await self.dispatch(job)
        return job, created

    async def create(
        self,
        *,
        job_type: str,
        principal: Principal,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        normalized_payload = self._normalize_payload(job_type, payload)
        return await self.store.enqueue(
            job_type=job_type,
            requester=principal,
            idempotency_key=idempotency_key,
            input_payload=normalized_payload,
            max_retries=2,
        )

    async def submit_reconcile(
        self,
        *,
        principal: Principal,
        idempotency_key: str,
        mode: str,
        approval_id: str,
    ) -> tuple[dict[str, Any], bool]:
        payload = self._normalize_payload("trade.reconcile", {"mode": mode})
        try:
            async with get_db() as db:
                job, created = await self.store.enqueue(
                    job_type="trade.reconcile",
                    requester=principal,
                    idempotency_key=idempotency_key,
                    input_payload=payload,
                    max_retries=2,
                    db=db,
                )
                if created:
                    approval = await ExecutionAuthorizationService().consume_operation_approval(
                        db,
                        approval_id=approval_id,
                        principal=principal,
                        action_type="trade.reconcile",
                        payload=payload,
                        job_id=str(job["job_id"]),
                    )
                    await self.store.bind_operation_approval(
                        db,
                        job_id=str(job["job_id"]),
                        approval_id=str(approval["approval_id"]),
                    )
        except ExecutionAuthorizationError as exc:
            raise OperationJobApprovalError(
                exc.message, code=exc.code, status_code=exc.status_code
            ) from exc
        if created:
            job = await self.dispatch(job)
        return job, created

    async def dispatch(self, job: dict[str, Any]) -> dict[str, Any]:
        self._require_operation_job(job)
        try:
            dispatch_operation_job(str(job["job_id"]), str(job["job_type"]))
        except OperationJobDispatchError:
            return await self.store.mark_dispatch_pending(
                job["job_id"], error_code="OPERATION_JOB_DISPATCH_PENDING"
            )
        return await self.store.mark_dispatch_accepted(job["job_id"])

    async def block_before_dispatch(self, job_id: str, *, error_code: str) -> None:
        await self.store.mark_dispatch_blocked(job_id, error_code=error_code)

    async def get_status(self, job_id: str, principal: Principal) -> dict[str, Any]:
        job = await self.store.get(job_id, principal)
        self._require_operation_job(job)
        return job

    async def get_result(self, job_id: str, principal: Principal) -> dict[str, Any]:
        result = await self.store.get_result(job_id, principal)
        self._require_operation_job(result["job"])
        return result

    async def cancel(self, job_id: str, principal: Principal) -> dict[str, Any]:
        await self.get_status(job_id, principal)
        return await self.store.request_cancel(job_id, principal)

    async def execute(self, job_id: str, worker: Principal) -> dict[str, Any]:
        if worker.principal_type != "service" or worker.role != "service_worker":
            raise OperationJobWorkerForbidden("仅 service_worker 凭据可执行操作任务")
        job = await self.store.get(job_id, worker)
        self._require_operation_job(job)
        claimed = await self.store.claim(
            job_id, worker, lease_seconds=_OPERATION_LEASE_SECONDS
        )
        if claimed is None:
            return await self.store.get(job_id, worker)
        lease_token = str(claimed.get("lease_token") or "")
        stage = "job_claimed"
        try:
            self._require_operation_job(claimed)
            if not lease_token:
                raise AsyncJobStateError("操作任务缺少有效租约")
            cancelled = await self.store.cancel_if_requested(
                job_id, lease_token=lease_token
            )
            if cancelled is not None:
                return cancelled
            await self.store.update_progress(
                job_id,
                10,
                lease_token=lease_token,
                lease_seconds=_OPERATION_LEASE_SECONDS,
            )
            stage = "backend_operation_started"
            await self.store.mark_stage(job_id, stage)
            result = await self._execute_claimed(claimed, lease_token=lease_token)
            await self.store.mark_stage(job_id, "job_success")
            return await self.store.complete_with_result(
                job_id, result, lease_token=lease_token
            )
        except OperationJobPermanentFailure as exc:
            return await self.store.mark_failure(
                job_id,
                error_code=exc.code,
                retryable=False,
                lease_token=lease_token,
                error_type=type(exc).__name__,
                error_message=str(exc),
                error_stage=stage,
                traceback_summary="".join(
                    traceback.format_exception_only(type(exc), exc)
                ).strip(),
            )
        except OperationJobInputError as exc:
            return await self.store.mark_failure(
                job_id, error_code=exc.code, retryable=False, lease_token=lease_token
            )
        except AsyncJobError:
            return await self.store.get(job_id, worker)
        except Exception as exc:
            return await self.store.mark_failure(
                job_id,
                error_code="OPERATION_JOB_EXECUTION_RETRYABLE",
                retryable=True,
                lease_token=lease_token,
                error_type=type(exc).__name__,
                error_message=str(exc),
                error_stage=stage,
                traceback_summary="".join(traceback.format_exception_only(type(exc), exc)).strip(),
            )

    async def recover_and_dispatch(self, *, limit: int = 100) -> dict[str, int]:
        recovered = await self.store.recover_expired_leases(
            job_types=set(OPERATION_JOB_TYPES), limit=limit
        )
        dispatchable = await self.store.list_dispatchable(
            job_types=set(OPERATION_JOB_TYPES), limit=limit
        )
        accepted = 0
        pending = 0
        for job in dispatchable:
            outcome = await self.dispatch(job)
            if outcome.get("error_code") == "OPERATION_JOB_DISPATCH_PENDING":
                pending += 1
            else:
                accepted += 1
        return {
            "recovered": len(recovered),
            "dispatch_accepted": accepted,
            "dispatch_pending": pending,
        }

    async def _execute_claimed(
        self, claimed: dict[str, Any], *, lease_token: str
    ) -> dict[str, Any]:
        job_type = str(claimed["job_type"])
        payload = self._normalize_payload(job_type, claimed["input_payload"])
        if job_type == "market.sync_universe":
            return await self._sync_universe(payload, job_id=str(claimed["job_id"]))
        if job_type == "market.backfill_kline":
            return await self._backfill_kline(payload)
        if job_type == "ai.analyze":
            return await self._analyze_stock(payload)
        if job_type == "trade.orders_sync":
            return await self._sync_open_orders(payload)
        if job_type == "trade.reconcile":
            await self._verify_reconcile_approval(claimed, payload)
            return await self._reconcile_broker(payload)
        raise OperationJobUnsupported("未知操作任务类型")

    @staticmethod
    def _require_operation_job(job: dict[str, Any]) -> None:
        if str(job.get("job_type")) not in OPERATION_JOB_TYPES:
            raise OperationJobUnsupported("该任务不属于操作任务模型")

    @staticmethod
    def _normalize_payload(job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if job_type not in OPERATION_JOB_TYPES:
            raise OperationJobUnsupported("未知操作任务类型")
        if not isinstance(payload, dict):
            raise OperationJobInputError("操作任务载荷必须是对象")
        if job_type == "market.sync_universe":
            backfill_top_n = int(payload.get("backfill_top_n", 50))
            if not 0 <= backfill_top_n <= 200:
                raise OperationJobInputError("backfill_top_n 超出允许范围")
            return {
                "backfill_top_n": backfill_top_n,
                "allow_synthetic": bool(payload.get("allow_synthetic", False)),
            }
        if job_type == "market.backfill_kline":
            raw_codes = payload.get("codes", [])
            if not isinstance(raw_codes, list):
                raise OperationJobInputError("codes 必须是数组")
            codes = [
                str(code).strip()
                for code in raw_codes
                if code is not None and str(code).strip()
            ]
            if not codes or len(codes) > 200:
                raise OperationJobInputError("codes 必须为 1 至 200 个有效标的")
            limit = int(payload.get("limit", 250))
            concurrency = int(payload.get("concurrency", 5))
            if not 10 <= limit <= 1000 or not 1 <= concurrency <= 20:
                raise OperationJobInputError("回填参数超出允许范围")
            return {
                "codes": codes,
                "period": str(payload.get("period", "1d")),
                "limit": limit,
                "allow_synthetic": bool(payload.get("allow_synthetic", False)),
                "start_date": payload.get("start_date"),
                "end_date": payload.get("end_date"),
                "concurrency": concurrency,
            }
        if job_type == "ai.analyze":
            code = str(payload.get("code", "")).strip()
            if not code:
                raise OperationJobInputError("code 不能为空")
            strategy_id = payload.get("strategy_id")
            if strategy_id is not None and int(strategy_id) <= 0:
                raise OperationJobInputError("strategy_id 必须为正整数")
            return {
                "code": code,
                "force_refresh": bool(payload.get("force_refresh", False)),
                "strategy_id": int(strategy_id) if strategy_id is not None else None,
            }
        mode = str(payload.get("mode", ""))
        if mode not in {"paper", "live"}:
            raise OperationJobInputError("mode 必须为 paper 或 live")
        return {"mode": mode}

    async def _sync_universe(self, payload: dict[str, Any], *, job_id: str) -> dict[str, Any]:
        seed_path = Path(__file__).resolve().parents[2] / "scripts" / "seed_stocks.py"
        spec = importlib.util.spec_from_file_location("seed_stocks_mod", seed_path)
        if spec is None or spec.loader is None:
            raise OperationJobInputError("无法加载股票池同步脚本")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        await self.store.mark_stage(job_id, "stock_refresh_request_started")
        await module.seed_stocks(refresh_source=True)
        await self.store.mark_stage(job_id, "database_write_completed")

        backfill_top_n = int(payload["backfill_top_n"])
        async with get_db() as db:
            total = int(
                await db.scalar(
                    text("SELECT COUNT(*) FROM fundamental.stocks WHERE is_active=TRUE")
                )
                or 0
            )
            rows = await db.execute(
                text(
                    """
                    SELECT code FROM fundamental.stocks
                    WHERE is_active=TRUE ORDER BY code LIMIT :n
                    """
                ),
                {"n": backfill_top_n},
            )
            codes = [row[0] for row in rows.fetchall()]

        backfill = None
        if codes and backfill_top_n > 0:
            service = KlineBackfillService()
            try:
                backfill = await service.backfill_codes(
                    codes,
                    period="1d",
                    limit=250,
                    allow_synthetic=bool(payload["allow_synthetic"]),
                    concurrency=8,
                )
            finally:
                await service.close()
        return {"total_active": total, "backfill": backfill}

    async def _backfill_kline(self, payload: dict[str, Any]) -> dict[str, Any]:
        start_date = self._as_date(payload.get("start_date"))
        end_date = self._as_date(payload.get("end_date"))
        limit = int(payload["limit"])
        if start_date and end_date:
            limit = max(limit, estimate_limit_for_range(start_date, end_date))
        service = KlineBackfillService()
        try:
            result = await service.backfill_codes(
                list(payload["codes"]),
                period=str(payload["period"]),
                limit=limit,
                concurrency=int(payload["concurrency"]),
                allow_synthetic=bool(payload["allow_synthetic"]),
                start_date=start_date,
                end_date=end_date,
            )
            if int(result.get("success") or 0) == 0:
                raise OperationJobPermanentFailure(
                    "KLINE_BACKFILL_NO_DATA",
                    "K线回填未写入任何有效数据",
                )
            return result
        finally:
            await service.close()

    @staticmethod
    async def _analyze_stock(payload: dict[str, Any]) -> dict[str, Any]:
        from app.services.ai_service import AIService

        service = AIService()
        try:
            result = await service.analyze(
                str(payload["code"]),
                force_refresh=bool(payload["force_refresh"]),
                strategy_id=payload["strategy_id"],
            )
            return result.model_dump()
        finally:
            await service.close()

    @staticmethod
    async def _sync_open_orders(payload: dict[str, Any]) -> dict[str, Any]:
        from app.services.trade_service import TradeService

        return await TradeService().sync_open_orders(str(payload["mode"]))

    @staticmethod
    async def _reconcile_broker(payload: dict[str, Any]) -> dict[str, Any]:
        from app.services.trade_service import TradeService

        return await TradeService().reconcile_with_broker(str(payload["mode"]))

    @staticmethod
    async def _verify_reconcile_approval(
        claimed: dict[str, Any], payload: dict[str, Any]
    ) -> None:
        approval_id = str(claimed.get("operation_approval_id") or "")
        requester_principal_id = str(claimed.get("requester_principal_id") or "")
        job_id = str(claimed.get("job_id") or "")
        if not approval_id or not requester_principal_id or not job_id:
            raise OperationJobApprovalError("对账任务缺少审批绑定")
        try:
            async with get_db() as db:
                await ExecutionAuthorizationService().verify_consumed_operation_approval(
                    db,
                    approval_id=approval_id,
                    requester_principal_id=requester_principal_id,
                    action_type="trade.reconcile",
                    payload=payload,
                    job_id=job_id,
                )
        except ExecutionAuthorizationError as exc:
            raise OperationJobApprovalError(
                exc.message, code=exc.code, status_code=exc.status_code
            ) from exc

    @staticmethod
    def _as_date(value: object) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise OperationJobInputError("日期格式无效") from exc
