from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data.free_observation_strategy_snapshot import (
    FreeObservationStrategySnapshotError,
    FreeObservationStrategySnapshotExporter,
)
from app.db import get_db


async def export_snapshot() -> dict[str, object]:
    async with get_db() as db:
        return await FreeObservationStrategySnapshotExporter().export(db)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export one read-only governed dual_ma snapshot for local free observation.")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--confirm-free-observation", action="store_true")
    args = parser.parse_args()
    if not args.confirm_free_observation:
        print("必须显式传入 --confirm-free-observation；本命令只读策略治理记录。", file=sys.stderr)
        return 2
    if os.environ.get("APP_ENV", "development").strip().lower() == "production":
        print("免费观测策略快照仅允许 local_development，拒绝 production。", file=sys.stderr)
        return 2
    try:
        snapshot = asyncio.run(export_snapshot())
        serialized = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
            stream.write("\n")
        print(serialized)
        return 0
    except FileExistsError:
        print(f"策略快照文件已存在，拒绝覆盖：{args.output}", file=sys.stderr)
        return 2
    except FreeObservationStrategySnapshotError as exc:
        print(f"免费观测策略快照导出失败（fail-closed，{exc.code}）：{exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("免费观测策略快照导出失败（fail-closed，FREE_OBSERVATION_STRATEGY_UNAVAILABLE）：策略治理数据库不可用", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
