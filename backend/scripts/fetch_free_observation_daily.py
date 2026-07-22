from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data.tushare_free_observation import FreeObservationError, TushareFreeObservationClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch an explicit local free-observation daily batch.")
    parser.add_argument("--trade-date", required=True, type=date.fromisoformat)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--confirm-free-observation", action="store_true")
    args = parser.parse_args()
    if not args.confirm_free_observation:
        print("必须显式传入 --confirm-free-observation；本命令不会启动正式 P3/P4 或交易。", file=sys.stderr)
        return 2
    if os.environ.get("APP_ENV", "development").strip().lower() == "production":
        print("免费观测抓取仅允许 local_development，拒绝 production。", file=sys.stderr)
        return 2
    try:
        client = TushareFreeObservationClient(token=os.environ.get("TUSHARE_TOKEN", ""))
        try:
            batch = client.fetch_daily(trade_date=args.trade_date)
        finally:
            client.close()
        serialized = json.dumps(batch.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
            stream.write("\n")
        print(serialized)
        return 0
    except FileExistsError:
        print(f"观测文件已存在，拒绝覆盖：{args.output}", file=sys.stderr)
        return 2
    except FreeObservationError as exc:
        print(f"免费观测抓取失败（fail-closed，{exc.code}）：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
