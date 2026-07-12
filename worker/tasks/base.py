from __future__ import annotations

from celery import Task

from logging_setup import get_logger

logger = get_logger(__name__, feature="worker")


class LoggingTask(Task):
    """Celery Task 基类：统一成功/失败/重试日志。"""

    abstract = True

    def __call__(self, *args, **kwargs):
        logger.info(
            "task_start",
            task=self.name,
            args_preview=str(args)[:200],
            kwargs_preview=str(kwargs)[:200],
        )
        return super().__call__(*args, **kwargs)

    def on_success(self, retval, task_id, args, kwargs) -> None:
        logger.info(
            "task_success",
            task=self.name,
            task_id=task_id,
            result_preview=str(retval)[:300] if retval is not None else None,
        )

    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:
        logger.error(
            "task_failure",
            task=self.name,
            task_id=task_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )

    def on_retry(self, exc, task_id, args, kwargs, einfo) -> None:
        logger.warning(
            "task_retry",
            task=self.name,
            task_id=task_id,
            error=str(exc),
        )