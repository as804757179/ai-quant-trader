"""全局日志：structlog + 功能域标签 + 请求上下文。

约定：
- event 名用 snake_case，如 trade_order_created / risk_fuse_activated
- 业务日志尽量绑定 feature= 功能域，便于按模块过滤排查
- HTTP 层由 main 中间件统一打 request_start / request_end（含 request_id）
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, get_contextvars

# ── 功能域（与项目文档模块对齐）────────────────────────────────
FEATURE_SYSTEM = "system"
FEATURE_STOCK = "stock"
FEATURE_DATA = "data"
FEATURE_AI = "ai"
FEATURE_SCREENER = "screener"
FEATURE_STRATEGY = "strategy"
FEATURE_BACKTEST = "backtest"
FEATURE_TRADE = "trade"
FEATURE_PORTFOLIO = "portfolio"
FEATURE_RISK = "risk"
FEATURE_NOTIFY = "notify"
FEATURE_WS = "ws"
FEATURE_MONITOR = "monitor"
FEATURE_RAG = "rag"
FEATURE_WORKER = "worker"

_PATH_FEATURE_RULES: list[tuple[str, str]] = [
    ("/api/v1/stock", FEATURE_STOCK),
    ("/api/v1/ai", FEATURE_AI),
    ("/api/v1/screener", FEATURE_SCREENER),
    ("/api/v1/strategy", FEATURE_STRATEGY),
    ("/api/v1/backtest", FEATURE_BACKTEST),
    ("/api/v1/trade", FEATURE_TRADE),
    ("/api/v1/portfolio", FEATURE_PORTFOLIO),
    ("/api/v1/risk", FEATURE_RISK),
    ("/ws/", FEATURE_WS),
    ("/ws", FEATURE_WS),
    ("/metrics", FEATURE_MONITOR),
    ("/api/v1/health", FEATURE_MONITOR),
    ("/api/docs", FEATURE_SYSTEM),
    ("/api/redoc", FEATURE_SYSTEM),
    ("/api/openapi", FEATURE_SYSTEM),
]

_QUIET_PATH_PREFIXES = (
    "/metrics",
    "/api/v1/health",
    "/api/docs",
    "/api/redoc",
    "/api/openapi",
    "/favicon.ico",
)


def feature_from_path(path: str) -> str:
    if not path:
        return FEATURE_SYSTEM
    for prefix, feature in _PATH_FEATURE_RULES:
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
            return feature
        if path.startswith(prefix) and (
            len(path) == len(prefix) or path[len(prefix)] in "/?"
        ):
            return feature
    if path.startswith("/api/"):
        return FEATURE_SYSTEM
    return FEATURE_SYSTEM


def is_quiet_path(path: str) -> bool:
    return any(path == p or path.startswith(p) for p in _QUIET_PATH_PREFIXES)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def bind_request_context(
    *,
    request_id: str,
    method: str,
    path: str,
    feature: str | None = None,
    client: str | None = None,
) -> None:
    bind_contextvars(
        request_id=request_id,
        http_method=method,
        http_path=path,
        feature=feature or feature_from_path(path),
        client=client or "",
    )


def clear_request_context() -> None:
    clear_contextvars()


def get_bound_context() -> dict[str, Any]:
    return dict(get_contextvars())


def setup_logging() -> None:
    """初始化全局 structlog + stdlib logging。

    使用 stdlib BoundLogger + 简单 Console/JSON Renderer，
    避免 ProcessorFormatter + filter_by_level 在 foreign logs 上触发
    ``NoneType.isEnabledFor``。
    """
    try:
        from app.core.config import settings

        level_name = (settings.LOG_LEVEL or "INFO").upper()
        is_prod = settings.is_production()
    except Exception:
        import os

        level_name = os.getenv("LOG_LEVEL", "INFO").upper()
        is_prod = os.getenv("APP_ENV", "").lower() == "production"

    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn.access", "httpx", "httpcore", "asyncio", "sqlalchemy.engine"):
        logging.getLogger(name).setLevel(max(level, logging.WARNING))

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]
    if is_prod:
        processors.append(structlog.processors.JSONRenderer(ensure_ascii=False))
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(handlers=[handler], level=level, force=True)


def get_logger(name: str | None = None, *, feature: str | None = None) -> Any:
    log = structlog.get_logger(name or __name__)
    if feature:
        return log.bind(feature=feature)
    return log


@contextmanager
def feature_context(feature: str, **extra: Any) -> Iterator[Any]:
    prev = get_contextvars()
    bind_contextvars(feature=feature, **extra)
    try:
        yield get_logger(feature=feature)
    finally:
        clear_contextvars()
        if prev:
            bind_contextvars(**prev)


logger = get_logger("app", feature=FEATURE_SYSTEM)
