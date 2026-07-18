"""Dispatch persisted operation Jobs through the existing Celery broker."""

from celery import Celery
from kombu import Exchange, Queue

from app.core.config import settings


OPERATION_JOB_TASK = "tasks.execute_operation_job"
_JOB_QUEUES = {
    "market.sync_universe": "low",
    "market.backfill_kline": "low",
    "ai.analyze": "normal",
    "trade.orders_sync": "high",
    "trade.reconcile": "low",
}
_OPERATION_EXCHANGE = Exchange("quant_trader", type="direct")
_OPERATION_QUEUES = {
    name: Queue(name, exchange=_OPERATION_EXCHANGE, routing_key=name)
    for name in ("high", "normal", "low")
}


class OperationJobDispatchError(Exception):
    """Raised after a persisted Job cannot be handed to the existing broker."""


def dispatch_operation_job(job_id: str, job_type: str) -> None:
    queue = _JOB_QUEUES.get(job_type)
    if queue is None:
        raise OperationJobDispatchError("未知操作任务类型")
    try:
        client = Celery("quant_trader", broker=settings.REDIS_URL)
        client.conf.update(
            broker_connection_timeout=3,
            task_queues=tuple(_OPERATION_QUEUES.values()),
            task_default_exchange="quant_trader",
            task_default_exchange_type="direct",
            task_default_routing_key=queue,
        )
        client.send_task(
            OPERATION_JOB_TASK,
            args=[job_id],
            queue=_OPERATION_QUEUES[queue],
            routing_key=queue,
        )
    except Exception as exc:
        raise OperationJobDispatchError("操作任务无法投递到 Worker") from exc
