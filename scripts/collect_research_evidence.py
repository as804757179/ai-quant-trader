"""Explicitly collect one observed-only research-evidence batch."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))


def load_env_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"缺少环境文件：{path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


async def collect(symbol: str, limit: int, data_service_url: str) -> dict:
    from services.research_evidence_sync import ResearchEvidenceSyncService

    service = ResearchEvidenceSyncService(data_service_url=data_service_url)
    return await service.sync_symbols([symbol], limit=limit)


def main() -> int:
    parser = argparse.ArgumentParser(description="采集只读公告研究证据")
    parser.add_argument("--symbol", default="000001.SZ")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--data-service-url", default="http://127.0.0.1:8080")
    parser.add_argument("--env-file", default=str(ROOT / ".env.host"))
    args = parser.parse_args()
    try:
        load_env_file(Path(args.env_file))
        print(f"开始采集只读公告证据：{args.symbol}")
        result = asyncio.run(collect(args.symbol, max(1, min(args.limit, 5)), args.data_service_url))
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0 if all(item["status"] in {"success", "partial"} for item in result["results"]) else 1
    except Exception as exc:
        print(f"公告证据采集失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
