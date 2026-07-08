"""系统健康检查脚本"""

import asyncio
import os
import sys


async def check_database() -> None:
    from sqlalchemy import text

    from app.db import engine

    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT version()"))
        version = result.scalar()
        print(f"✅ PostgreSQL: {str(version)[:50]}")


async def check_redis() -> None:
    import redis.asyncio as aioredis

    r = aioredis.from_url(os.getenv("REDIS_URL", ""))
    pong = await r.ping()
    print(f"✅ Redis: {'PONG' if pong else 'FAILED'}")
    await r.aclose()


async def check_timescaledb() -> None:
    from sqlalchemy import text

    from app.db import engine

    async with engine.begin() as conn:
        result = await conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
        )
        version = result.scalar()
        print(f"✅ TimescaleDB: {version}")


async def check_ai_keys() -> None:
    from app.core.config import settings

    available = settings.validate_ai_keys()
    for service, is_available in available.items():
        status = "✅" if is_available else "❌"
        label = "配置" if is_available else "未配置"
        print(f"{status} AI Key: {service} {label}")


async def check_chromadb() -> None:
    import chromadb

    client = chromadb.PersistentClient(
        path=os.getenv("CHROMA_PERSIST_DIR", "/app/vector_db")
    )
    collections = client.list_collections()
    print(f"✅ ChromaDB: {len(collections)} collections")


async def main() -> None:
    print("=== AI Quant Trader Pro 系统健康检查 ===\n")
    checks = [
        ("数据库", check_database),
        ("Redis", check_redis),
        ("TimescaleDB", check_timescaledb),
        ("AI Keys", check_ai_keys),
        ("ChromaDB", check_chromadb),
    ]

    failed: list[str] = []
    for name, check_fn in checks:
        try:
            await check_fn()
        except Exception as exc:
            print(f"❌ {name}: {exc}")
            failed.append(name)

    print(f"\n{'=' * 40}")
    if failed:
        print(f"❌ {len(failed)} 项检查失败: {', '.join(failed)}")
        sys.exit(1)
    print("✅ 所有检查通过，系统就绪")


if __name__ == "__main__":
    asyncio.run(main())