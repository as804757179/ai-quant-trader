from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
for raw_line in (ROOT / ".env.host").read_text(encoding="utf-8-sig").splitlines():
    line = raw_line.strip()
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

from app.data.sohu_daily_importer import SohuDailyKlineImporter  # noqa: E402

ALLOWED_SYMBOLS = ("300308.SZ", "603986.SH", "300502.SZ")


async def run() -> int:
    parser = argparse.ArgumentParser(description="Import the fixed Sprint06 certified K-line pilot")
    parser.add_argument("--start", default="2026-06-01")
    parser.add_argument("--end", default="2026-06-30")
    args = parser.parse_args()
    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)
    if start_date != date(2026, 6, 1) or end_date != date(2026, 6, 30):
        raise SystemExit("Sprint06 pilot only permits 2026-06-01 through 2026-06-30")

    importer = SohuDailyKlineImporter()
    try:
        results = [
            await importer.import_code(symbol, start_date, end_date)
            for symbol in ALLOWED_SYMBOLS
        ]
    finally:
        await importer.close()
    print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    return 0 if any(result.status == "certified" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
