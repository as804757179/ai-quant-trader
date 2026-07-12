import asyncio
import os
from pathlib import Path

from sqlalchemy import text

# load .env.host
root = Path(__file__).resolve().parents[1]
for line in (root / ".env.host").read_text(encoding="utf-8").splitlines():
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k, v)

from app.db import engine  # noqa: E402


async def main() -> None:
    async with engine.connect() as c:
        r = await c.execute(
            text(
                "select schema_name from information_schema.schemata "
                "where schema_name in ('market','trade','risk','ai','backtest','fundamental') "
                "order by 1"
            )
        )
        print("schemas:", [x[0] for x in r])


if __name__ == "__main__":
    asyncio.run(main())
