"""Asynchronous, fail-closed orchestration for persisted backtest jobs."""

from __future__ import annotations

from typing import Any

from app.backtest.service import BacktestService, BacktestStrategyDisabled
from app.core.auth import Principal
from app.core.config import settings
from app.jobs.service import (
    AsyncJobError,
    AsyncJobStore,
)


BACKTEST_JOB_TYPE = "backtest.run"


class BacktestWorkerForbidden(AsyncJobError):
    code = "BACKTEST_WORKER_FORBIDDEN"
    status_code = 403


class BacktestResultUnavailable(AsyncJobError):
    code = "JOB_RESULT_UNAVAILABLE"
    status_code = 409


class BacktestJobService:
    """Queue and execute backtests without allowing HTTP request execution.

    A caller may create an auditable job only.  The execution method is for a
    provisioned service principal and deliberately re-checks every release and
    trusted-input boundary before delegating to the existing backtest service.
    """

    def __init__(
        self,
        *,
        store: AsyncJobStore | None = None,
        backtest_service: BacktestService | None = None,
    ) -> None:
        self.store = store or AsyncJobStore()
        self.backtest_service = backtest_service or BacktestService()

    async def enqueue(
        self,
        *,
        principal: Principal,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        self.backtest_service.validate_submission_input(**payload)
        strategy_snapshot = await self.backtest_service.resolve_enabled_strategy_snapshot(
            strategy_type=payload["strategy_type"],
            params=payload.get("params"),
        )
        governed_payload = {
            **payload,
            "strategy_config_snapshot": strategy_snapshot,
        }
        locked = not settings.CERTIFIED_BACKTEST_EXECUTION_ENABLED
        return await self.store.enqueue(
            job_type=BACKTEST_JOB_TYPE,
            requester=principal,
            idempotency_key=idempotency_key,
            input_payload=governed_payload,
            initial_status="blocked" if locked else "queued",
            initial_error_code=(
                "CERTIFIED_BACKTEST_EXECUTION_DISABLED" if locked else None
            ),
            max_retries=2,
        )

    async def get_status(self, job_id: str, principal: Principal) -> dict[str, Any]:
        return await self.store.get(job_id, principal)

    async def cancel(self, job_id: str, principal: Principal) -> dict[str, Any]:
        return await self.store.request_cancel(job_id, principal)

    async def execute(self, job_id: str, worker: Principal) -> dict[str, Any]:
        if worker.principal_type != "service" or worker.role != "service_worker":
            raise BacktestWorkerForbidden("仅 service_worker 凭据可执行回测任务")

        claimed = await self.store.claim(job_id, worker)
        if claimed is None:
            return await self.store.get(job_id, worker)
        if not settings.CERTIFIED_BACKTEST_EXECUTION_ENABLED:
            return await self.store.mark_blocked(
                job_id, error_code="CERTIFIED_BACKTEST_EXECUTION_DISABLED"
            )

        payload = claimed["input_payload"]
        try:
            await self.store.update_progress(job_id, 10)
            await self.backtest_service.verify_strategy_snapshot(
                payload.get("strategy_config_snapshot")
            )
            result = await self.backtest_service.create_and_run(**payload)
        except BacktestStrategyDisabled as exc:
            return await self.store.mark_failure(
                job_id,
                error_code=exc.code,
                retryable=False,
            )
        except ValueError:
            return await self.store.mark_failure(
                job_id,
                error_code="BACKTEST_TRUSTED_INPUT_REJECTED",
                retryable=False,
            )
        except Exception:
            return await self.store.mark_failure(
                job_id,
                error_code="BACKTEST_EXECUTION_RETRYABLE",
                retryable=True,
            )

        task_id = result.get("task_id")
        if not isinstance(task_id, int) or task_id <= 0:
            return await self.store.mark_failure(
                job_id,
                error_code="BACKTEST_RESULT_REFERENCE_MISSING",
                retryable=False,
            )
        return await self.store.mark_succeeded(
            job_id, result_ref=f"backtest.tasks:{task_id}"
        )

    async def get_result(self, job_id: str, principal: Principal) -> dict[str, Any]:
        job = await self.store.get(job_id, principal)
        if job["status"] != "succeeded" or not job["result_ref"]:
            raise BacktestResultUnavailable("任务尚未产生可读取的回测结果")
        prefix, separator, raw_task_id = str(job["result_ref"]).partition(":")
        if prefix != "backtest.tasks" or not separator or not raw_task_id.isdigit():
            raise BacktestResultUnavailable("任务结果引用不可验证")
        result = await self.backtest_service.get_result(int(raw_task_id))
        return {"job": job, "result": result}
