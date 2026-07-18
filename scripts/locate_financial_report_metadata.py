"""Parse fixed local financial-report snapshots and persist page locations."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


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
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


async def run(evidence_ids: list[UUID]) -> dict:
    from services.financial_report_page_locator import (
        FinancialReportPageLocationStore,
        extract_pdf_pages,
        locate_metadata,
    )

    store = FinancialReportPageLocationStore()
    results = []
    try:
        for evidence_id in evidence_ids:
            candidate = await store.get_candidate(evidence_id)
            if candidate.get("existing_parse_run_id") is not None:
                results.append(await store.persist(candidate, [], [], datetime.now(timezone.utc), False))
                continue
            started_at = datetime.now(timezone.utc)
            pages, encrypted = await asyncio.to_thread(extract_pdf_pages, candidate["path"])
            locations = locate_metadata(pages)
            result = await store.persist(candidate, pages, locations, started_at, encrypted)
            result["evidence_id"] = str(evidence_id)
            result["stock_code"] = candidate["stock_code"]
            results.append(result)
    finally:
        await store.close()
    return {"parser": "pypdf", "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="定位两份固定年报的页级元数据证据")
    parser.add_argument(
        "--evidence-id",
        action="append",
        choices=(
            "cef779d8-96d7-4a01-8ae3-2b9a023447e0",
            "522d97a3-ff33-4001-81da-6575cd4ad8e3",
        ),
    )
    parser.add_argument("--env-file", default=str(ROOT / ".env.host"))
    args = parser.parse_args()
    evidence_ids = [
        UUID(value)
        for value in (
            args.evidence_id
            or [
                "cef779d8-96d7-4a01-8ae3-2b9a023447e0",
                "522d97a3-ff33-4001-81da-6575cd4ad8e3",
            ]
        )
    ]
    try:
        load_env_file(Path(args.env_file))
        print(json.dumps(asyncio.run(run(evidence_ids)), ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(f"财报页级定位失败：{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
