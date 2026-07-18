"""Worker execution for persisted operation Jobs."""

from __future__ import annotations

import structlog

from celery_app import app
from tasks.base import LoggingTask

logger = structlog.get_logger(__name__)


@app.task(
    name="tasks.execute_operation_job",
    bind=True,
    base=LoggingTask,
    ignore_result=True,
    max_retries=2,
)
def execute_operation_job(self, job_id: str) -> dict:
    """Claim and execute one persisted Job with the provisioned Worker principal."""
    import asyncio

    from services.backend_client import worker_api_headers

    logger.info("task_start", task="execute_operation_job", task_id=self.request.id, job_id=job_id)

    async def _run() -> dict:
        from app.core.auth import AuthService
        from app.jobs.operations import OperationJobService
        from app.jobs.service import AsyncJobStateError

        principal = await AuthService().authenticate(
            worker_api_headers(), {}, allow_anonymous=False
        )
        service = OperationJobService()
        await service.store.mark_stage(
            job_id,
            "worker_authenticated",
            celery_task_id=str(self.request.id or "") or None,
        )
        try:
            return await service.execute(job_id, principal)
        except AsyncJobStateError:
            current = await service.get_status(job_id, principal)
            if current["status"] in {"running", "succeeded", "failed", "cancelled", "blocked"}:
                logger.info(
                    "operation_job_duplicate_ignored",
                    task_id=self.request.id,
                    job_id=job_id,
                    status=current["status"],
                )
                return current
            raise

    try:
        result = asyncio.run(_run())
    except Exception as exc:
        logger.error(
            "operation_job_task_error",
            task_id=self.request.id,
            job_id=job_id,
            error_type=type(exc).__name__,
            exc_info=True,
        )
        raise
    return result


@app.task(
    name="tasks.recover_operation_jobs",
    bind=True,
    base=LoggingTask,
    ignore_result=True,
)
def recover_operation_jobs(self) -> dict:
    """Recover expired operation leases and redeliver durable queued Jobs."""
    import asyncio

    from app.jobs.operations import OperationJobService

    logger.info("task_start", task="recover_operation_jobs", task_id=self.request.id)
    return asyncio.run(OperationJobService().recover_and_dispatch())
