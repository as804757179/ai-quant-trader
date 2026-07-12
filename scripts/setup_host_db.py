"""在本机 PostgreSQL 上创建 quant_trader 库与 quant_admin 用户。"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]


def read_env_value(key: str) -> str:
    text = (ROOT / ".env").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith(f"{key}="):
            val = line.split("=", 1)[1]
            # docker-compose $$ escape -> single $
            return val.replace("$$", "$")
    raise KeyError(key)


async def main() -> None:
    password = read_env_value("DB_PASSWORD")
    user = "quant_admin"
    db = "quant_trader"
    admin_url = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"

    conn = await asyncpg.connect(admin_url)
    try:
        role_exists = await conn.fetchval(
            "SELECT 1 FROM pg_roles WHERE rolname = $1", user
        )
        # dollar-quote password to avoid # $ ' issues
        tag = "pwdtag"
        while tag in password:
            tag += "x"
        pwd_lit = f"${tag}${password}${tag}$"
        if role_exists:
            await conn.execute(f"ALTER ROLE {user} PASSWORD {pwd_lit}")
            print("role_password_updated")
        else:
            await conn.execute(f"CREATE ROLE {user} LOGIN PASSWORD {pwd_lit}")
            print("role_created")

        db_exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", db
        )
        if not db_exists:
            await conn.execute(f"CREATE DATABASE {db} OWNER {user}")
            print("database_created")
        else:
            await conn.execute(f"ALTER DATABASE {db} OWNER TO {user}")
            print("database_exists")
    finally:
        await conn.close()

    db_conn = await asyncpg.connect(
        f"postgresql://postgres:postgres@127.0.0.1:5432/{db}"
    )
    try:
        await db_conn.execute(f"GRANT ALL ON SCHEMA public TO {user}")
        await db_conn.execute(f"ALTER SCHEMA public OWNER TO {user}")
        print("grants_ok")
    finally:
        await db_conn.close()

    # verify login
    test = await asyncpg.connect(
        user=user, password=password, host="127.0.0.1", port=5432, database=db
    )
    try:
        print("login_ok", await test.fetchval("SELECT 1"))
    finally:
        await test.close()


if __name__ == "__main__":
    asyncio.run(main())
