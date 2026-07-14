"""Worker structlog 日志配置（与 backend 功能域约定对齐）。"""

from __future__ import annotations

import logging
import os
import sys

import structlog


def setup_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    root.addHandler(handler)
    root.setLevel(level)
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(max(level, logging.WARNING))

    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if os.getenv("APP_ENV", "").lower() == "production"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
            foreign_pre_chain=shared,
        )
    )
    logging.basicConfig(handlers=[handler], level=level, force=True)


def get_logger(name: str | None = None, *, feature: str = "worker"):
    return structlog.get_logger(name or __name__).bind(feature=feature)
