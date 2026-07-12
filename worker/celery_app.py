"""Celery 应用入口 — 队列、路由、Beat 调度、RedBeat。"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from config import get_broker_url, get_redis_url, get_result_backend
from logging_setup import setup_logging

setup_logging()

app = Celery("quant_trader")

# ── 队列定义 ──
default_exchange = Exchange("quant_trader", type="direct")
QUEUE_HIGH = Queue("high", exchange=default_exchange, routing_key="high")
QUEUE_NORMAL = Queue("normal", exchange=default_exchange, routing_key="normal")
QUEUE_LOW = Queue("low", exchange=default_exchange, routing_key="low")

app.conf.update(
    broker_url=get_broker_url(),
    result_backend=get_result_backend(),
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_queues=(QUEUE_HIGH, QUEUE_NORMAL, QUEUE_LOW),
    task_default_queue="normal",
    task_default_exchange="quant_trader",
    task_default_routing_key="normal",
    task_routes={
        "tasks.sync_realtime_quotes": {"queue": "high"},
        "tasks.sync_portfolio_value": {"queue": "high"},
        "tasks.run_signal_scan": {"queue": "normal"},
        "tasks.run_ai_analysis": {"queue": "normal"},
        "tasks.morning_screening": {"queue": "normal"},
        "tasks.sync_fund_flow": {"queue": "normal"},
        "tasks.update_available_quantity": {"queue": "normal"},
        "tasks.run_backtest_task": {"queue": "low"},
        "tasks.index_new_announcements": {"queue": "low"},
        "tasks.archive_daily_data": {"queue": "low"},
        "tasks.sync_live_positions_from_broker": {"queue": "low"},
        "tasks.take_eod_snapshot": {"queue": "low"},
        "tasks.weekly_full_data_sync": {"queue": "low"},
        "tasks.check_kline_completeness": {"queue": "low"},
        "tasks.reconcile_accounts": {"queue": "low"},
        "tasks.sync_open_orders": {"queue": "high"},
    },
    beat_schedule={
        "sync-quotes-3s": {
            "task": "tasks.sync_realtime_quotes",
            "schedule": 3.0,
            "options": {"queue": "high"},
        },
        "sync-open-orders-15s": {
            "task": "tasks.sync_open_orders",
            "schedule": 15.0,
            "options": {"queue": "high"},
        },
        "sync-portfolio-30s": {
            "task": "tasks.sync_portfolio_value",
            "schedule": 30.0,
            "options": {"queue": "high"},
        },
        "ai-signal-scan-1min": {
            "task": "tasks.run_signal_scan",
            "schedule": 60.0,
            "options": {"queue": "normal"},
        },
        "update-available-qty": {
            "task": "tasks.update_available_quantity",
            "schedule": crontab(hour=9, minute=25),
            "options": {"queue": "normal"},
        },
        "morning-screening-0915": {
            "task": "tasks.morning_screening",
            "schedule": crontab(hour=9, minute=15),
            "options": {"queue": "normal"},
        },
        "sync-fund-flow-30min": {
            "task": "tasks.sync_fund_flow",
            "schedule": 1800.0,
            "options": {"queue": "normal"},
        },
        "archive-daily-data-1530": {
            "task": "tasks.archive_daily_data",
            "schedule": crontab(hour=15, minute=30),
            "options": {"queue": "low"},
        },
        "sync-live-positions-1530": {
            "task": "tasks.sync_live_positions_from_broker",
            "schedule": crontab(hour=15, minute=35),
            "options": {"queue": "low"},
        },
        "reconcile-accounts-1600": {
            "task": "tasks.reconcile_accounts",
            "schedule": crontab(hour=16, minute=0),
            "options": {"queue": "low"},
        },
        "index-announcements-hourly": {
            "task": "tasks.index_new_announcements",
            "schedule": crontab(minute=0),
            "options": {"queue": "low"},
        },
        "daily-eod-snapshot": {
            "task": "tasks.take_eod_snapshot",
            "schedule": crontab(hour=16, minute=30),
            "options": {"queue": "low"},
        },
        "weekly-full-sync-sunday": {
            "task": "tasks.weekly_full_data_sync",
            "schedule": crontab(day_of_week=0, hour=2, minute=0),
            "options": {"queue": "low"},
        },
        "weekly-backfill-check": {
            "task": "tasks.check_kline_completeness",
            "schedule": crontab(day_of_week=0, hour=3, minute=0),
            "options": {"queue": "low"},
        },
    },
    beat_scheduler="redbeat.RedBeatScheduler",
    redbeat_redis_url=get_redis_url(),
    redbeat_key_prefix="redbeat:",
    worker_max_tasks_per_child=100,
    task_soft_time_limit=300,
    task_time_limit=600,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)

# 注册任务模块
app.autodiscover_tasks(["tasks"])

# 确保任务在 beat 启动前已加载
import tasks.ai  # noqa: E402, F401
import tasks.maintenance  # noqa: E402, F401
import tasks.market  # noqa: E402, F401