from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date

from app.data.certified_store_writer import CertifiedStoreWriter
from app.data.sohu_daily_importer import SohuDailyKlineImporter
from app.db import get_db


ALLOWED_CODES = {"603986.SH"}
START_DATE = date(2026, 6, 1)
END_DATE = date(2026, 6, 30)


async def run(stock_code: str) -> dict[str, object]:
    if stock_code not in ALLOWED_CODES:
        raise ValueError("Sprint07 importer is restricted to 603986.SH")
    importer = SohuDailyKlineImporter()
    try:
        fetched = await importer.fetch(stock_code, START_DATE, END_DATE)
        async with get_db() as db:
            result = await CertifiedStoreWriter().ingest(db, fetched)
    finally:
        await importer.close()
    return result.__dict__


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the Sprint07 certified-store pilot")
    parser.add_argument("--stock-code", default="603986.SH", choices=sorted(ALLOWED_CODES))
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.stock_code)), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
