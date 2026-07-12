"""全局日志：功能域推断与 logger 绑定。"""

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.core.logging import (
    FEATURE_AI,
    FEATURE_BACKTEST,
    FEATURE_MONITOR,
    FEATURE_RISK,
    FEATURE_STOCK,
    FEATURE_SYSTEM,
    FEATURE_TRADE,
    FEATURE_WS,
    feature_from_path,
    get_logger,
    is_quiet_path,
    new_request_id,
    setup_logging,
)


def test_feature_from_path_mapping():
    assert feature_from_path("/api/v1/stock/list") == FEATURE_STOCK
    assert feature_from_path("/api/v1/trade/order") == FEATURE_TRADE
    assert feature_from_path("/api/v1/ai/000001/analyze") == FEATURE_AI
    assert feature_from_path("/api/v1/backtest/run") == FEATURE_BACKTEST
    assert feature_from_path("/api/v1/risk/fuse-status") == FEATURE_RISK
    assert feature_from_path("/ws/alerts") == FEATURE_WS
    assert feature_from_path("/api/v1/health") == FEATURE_MONITOR
    assert feature_from_path("/metrics") == FEATURE_MONITOR
    assert feature_from_path("/unknown") == FEATURE_SYSTEM


def test_quiet_paths():
    assert is_quiet_path("/metrics")
    assert is_quiet_path("/api/v1/health")
    assert not is_quiet_path("/api/v1/trade/order")


def test_get_logger_and_setup():
    setup_logging()
    log = get_logger(__name__, feature=FEATURE_TRADE)
    log.info("test_logging_event", ok=True)
    rid = new_request_id()
    assert isinstance(rid, str) and len(rid) >= 8
