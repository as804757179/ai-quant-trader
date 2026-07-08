from __future__ import annotations

import structlog
from celery import Task

logger = structlog.get_logger(__name__)


class LoggingTask(Task):
    """Celery Task 基类：统一成功/失败/重试日志。"""

    abstract = True

    def on_success(self, retval, task_id, args, kwargs) -> None:
        logger.info("task_success", task=self.name, task_id=task_id)

    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:
        logger.error(
            "task_failure",
            task=self.name,
            task_id=task_id,
            error=str(exc),
        )

    def on_retry(self, exc, task_id, args, kwargs, einfo) -> None:
        logger.warning(
            "task_retry",
            task=self.name,
            task_id=task_id,
            error=str(exc),
        )