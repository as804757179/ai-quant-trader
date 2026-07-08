"""Worker 环境配置。"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def get_broker_url() -> str:
    return os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL", "")


def get_result_backend() -> str:
    return os.getenv("CELERY_RESULT_BACKEND") or get_broker_url()


def get_redis_url() -> str:
    return os.getenv("REDIS_URL", get_broker_url())


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "")