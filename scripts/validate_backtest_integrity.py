from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for raw in (ROOT / ".env.host").read_text(encoding="utf-8-sig").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()
sys.path.insert(0, str(ROOT / "backend"))

from app.backtest.integrity_validation import validate_backtest_integrity


if __name__ == "__main__":
    print(
        json.dumps(
            asyncio.run(validate_backtest_integrity()),
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
