"""Explicitly refetch and snapshot the two fixed financial report PDFs."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
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
        if key.strip():
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def fetch_pdf(document_url: str, timeout_seconds: int) -> tuple[bytes, str, datetime]:
    request = Request(
        document_url,
        headers={
            "User-Agent": "AIQuantTrader-FinancialSnapshot/1.0",
            "Referer": "https://www.cninfo.com.cn/",
            "Accept": "application/pdf",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        final_url = response.geturl()
        if final_url != document_url:
            raise ValueError(f"CNINFO PDF URL 发生未确认重定向：{final_url}")
        raw_document = response.read()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
    return raw_document, content_type, datetime.now(timezone.utc)


async def snapshot_one(store: object, evidence_id: UUID, timeout_seconds: int) -> dict:
    candidate = await store.get_candidate(evidence_id)
    try:
        existing = store.validate_existing_snapshot(candidate)
        if existing is not None:
            return existing
    except Exception as exc:
        return await store.persist_failure(
            candidate,
            status="validation_failed",
            failure_reason=f"既有本地快照校验失败：{type(exc).__name__}: {exc}",
        )
    try:
        raw_document, content_type, fetched_at = await asyncio.to_thread(
            fetch_pdf, str(candidate["document_url"]), timeout_seconds
        )
    except Exception as exc:
        return await store.persist_failure(
            candidate,
            status="fetch_failed",
            failure_reason=f"CNINFO PDF 显式读取失败：{type(exc).__name__}: {exc}",
        )
    observed_hash = hashlib.sha256(raw_document).hexdigest() if raw_document else None
    observed_bytes = len(raw_document) if raw_document else None
    try:
        return await store.persist_observed(
            candidate, raw_document, content_type, fetched_at
        )
    except RuntimeError as exc:
        status = "hash_mismatch" if "不一致" in str(exc) else "write_failed"
        return await store.persist_failure(
            candidate,
            status=status,
            failure_reason=str(exc),
            fetched_at=fetched_at,
            observed_raw_hash=observed_hash,
            observed_bytes=observed_bytes,
            content_type=content_type,
        )
    except ValueError as exc:
        return await store.persist_failure(
            candidate,
            status="validation_failed",
            failure_reason=str(exc),
            fetched_at=fetched_at,
            observed_raw_hash=observed_hash,
            observed_bytes=observed_bytes,
            content_type=content_type,
        )


async def run(evidence_ids: list[UUID], timeout_seconds: int) -> dict:
    from services.financial_report_snapshot_store import FinancialReportSnapshotStore

    store = FinancialReportSnapshotStore()
    try:
        results = []
        for evidence_id in evidence_ids:
            results.append(await snapshot_one(store, evidence_id, timeout_seconds))
    finally:
        await store.close()
    return {"acquisition_method": "explicit_refetch", "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="显式保管两份固定 CNINFO 年报原文快照")
    parser.add_argument(
        "--evidence-id",
        action="append",
        choices=(
            "cef779d8-96d7-4a01-8ae3-2b9a023447e0",
            "522d97a3-ff33-4001-81da-6575cd4ad8e3",
        ),
    )
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--env-file", default=str(ROOT / ".env.host"))
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 60:
        parser.error("--timeout-seconds 必须在 1 到 60 之间")
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
        result = asyncio.run(run(evidence_ids, args.timeout_seconds))
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0 if all(item["status"] == "observed" for item in result["results"]) else 1
    except Exception as exc:
        print(f"财报原文快照失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
