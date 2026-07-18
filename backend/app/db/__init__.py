from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

_engine_options = {
    "pool_pre_ping": True,
    "pool_recycle": 3600,
    # 全市场写入时 echo 会极慢；仅显式开启 SQL_ECHO=true
    "echo": bool(getattr(settings, "SQL_ECHO", False)),
}
if os.getenv("WORKER_ASYNC_NULL_POOL", "").lower() in {"1", "true", "yes"}:
    _engine_options["poolclass"] = NullPool
else:
    _engine_options["pool_size"] = settings.DB_POOL_SIZE
    _engine_options["max_overflow"] = settings.DB_MAX_OVERFLOW

engine = create_async_engine(settings.DATABASE_URL, **_engine_options)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db_dep() -> AsyncGenerator[AsyncSession, None]:
    async with get_db() as db:
        yield db
