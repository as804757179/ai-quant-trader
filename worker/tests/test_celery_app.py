import os

os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", os.environ["REDIS_URL"])
os.environ.setdefault("CELERY_RESULT_BACKEND", os.environ["REDIS_URL"])

from celery_app import app


def test_celery_app_name() -> None:
    assert app.main == "quant_trader"


def test_queue_configuration() -> None:
    queue_names = {q.name for q in app.conf.task_queues}
    assert queue_names == {"high", "normal", "low"}


def test_task_routes() -> None:
    routes = app.conf.task_routes
    assert routes["tasks.sync_realtime_quotes"]["queue"] == "high"
    assert routes["tasks.run_signal_scan"]["queue"] == "normal"
    assert routes["tasks.index_new_announcements"]["queue"] == "low"


def test_beat_schedule_exists() -> None:
    schedule = app.conf.beat_schedule
    assert "sync-quotes-3s" in schedule
    assert schedule["sync-quotes-3s"]["task"] == "tasks.sync_realtime_quotes"
    assert schedule["ai-signal-scan-1min"]["task"] == "tasks.run_signal_scan"


def test_redbeat_scheduler() -> None:
    assert app.conf.beat_scheduler == "redbeat.RedBeatScheduler"
    assert app.conf.redbeat_key_prefix == "redbeat:"


def test_tasks_registered() -> None:
    expected = {
        "tasks.sync_realtime_quotes",
        "tasks.run_signal_scan",
        "tasks.run_ai_analysis",
        "tasks.index_new_announcements",
        "tasks.archive_daily_data",
    }
    registered = set(app.tasks.keys())
    assert expected.issubset(registered)


def test_run_signal_scan_task_callable() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    service = MagicMock()
    service.scan_all = AsyncMock(return_value={"stocks_scanned": 0, "signals_generated": 0})
    service.close = AsyncMock()
    with patch("services.signal_scan.SignalScanService", return_value=service):
        task = app.tasks["tasks.run_signal_scan"]
        result = task.run()

    assert result["status"] == "ok"
    assert result["task"] == "run_signal_scan"
