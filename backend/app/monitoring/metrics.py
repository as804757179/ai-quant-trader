"""Prometheus 指标定义与导出。"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
)

# 独立 registry，避免多 worker 测试污染
REGISTRY = CollectorRegistry()

ALERTS_TOTAL = Counter(
    "quant_alerts_total",
    "告警累计次数",
    ["level", "type"],
    registry=REGISTRY,
)

ORDERS_TOTAL = Counter(
    "quant_orders_total",
    "订单状态累计（创建/更新时计数）",
    ["mode", "status"],
    registry=REGISTRY,
)

FUSE_ACTIVE = Gauge(
    "quant_risk_fuse_active",
    "熔断是否激活（1=激活 0=关闭）",
    ["mode"],
    registry=REGISTRY,
)

DINGTALK_SENT = Counter(
    "quant_dingtalk_sent_total",
    "钉钉推送次数",
    ["result"],
    registry=REGISTRY,
)

WS_CONNECTIONS = Gauge(
    "quant_ws_connections",
    "当前 WebSocket 连接数",
    registry=REGISTRY,
)

BACKTEST_TOTAL = Counter(
    "quant_backtest_total",
    "回测任务累计",
    ["status"],
    registry=REGISTRY,
)

BACKTEST_DURATION = Counter(
    "quant_backtest_duration_seconds_sum",
    "回测耗时累计秒",
    registry=REGISTRY,
)


def record_alert(level: str, alert_type: str) -> None:
    ALERTS_TOTAL.labels(
        level=(level or "INFO").upper(),
        type=(alert_type or "unknown")[:64],
    ).inc()


def record_order(mode: str, status: str) -> None:
    ORDERS_TOTAL.labels(mode=mode or "unknown", status=status or "unknown").inc()


def set_fuse_active(mode: str, active: bool) -> None:
    FUSE_ACTIVE.labels(mode=mode or "unknown").set(1 if active else 0)


def record_dingtalk(sent: bool) -> None:
    DINGTALK_SENT.labels(result="ok" if sent else "fail").inc()


def set_ws_connections(count: int) -> None:
    WS_CONNECTIONS.set(max(0, count))


def record_backtest(status: str, duration_seconds: float = 0.0) -> None:
    BACKTEST_TOTAL.labels(status=status or "unknown").inc()
    if duration_seconds > 0:
        BACKTEST_DURATION.inc(duration_seconds)


def metrics_response() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
