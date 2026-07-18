"""Explicitly collect the fixed Sprint14.8 official source documents."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
COLLECTOR_VERSION = "sprint14.8-source-terms-v1"


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


def fetch_document(terms_url: str, timeout_seconds: int) -> tuple[bytes, str, datetime]:
    request = Request(
        terms_url,
        headers={
            "User-Agent": "AIQuantTrader-SourceTermsAudit/1.0",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        final_url = response.geturl()
        if final_url != terms_url:
            raise ValueError(f"官方条款 URL 发生未确认重定向：{final_url}")
        raw_document = response.read()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
    return raw_document, content_type, datetime.now(timezone.utc)


async def collect(selected_provider: str, timeout_seconds: int) -> dict[str, object]:
    from services.research_source_usage_store import (
        ResearchSourceUsageStore,
        SOURCE_TERMS_DOCUMENTS,
    )

    documents = [
        item
        for item in SOURCE_TERMS_DOCUMENTS.values()
        if selected_provider == "all" or item.provider == selected_provider
    ]
    store = ResearchSourceUsageStore()
    results: list[dict[str, object]] = []
    try:
        for document in documents:
            try:
                raw_document, content_type, retrieved_at = await asyncio.to_thread(
                    fetch_document, document.terms_url, timeout_seconds
                )
                result = await store.append_observed_document(
                    terms_url=document.terms_url,
                    raw_document=raw_document,
                    content_type=content_type,
                    retrieved_at=retrieved_at,
                    collector_version=COLLECTOR_VERSION,
                )
            except Exception as exc:
                failure_status = (
                    "validation_failed" if isinstance(exc, ValueError) else "fetch_failed"
                )
                result = await store.append_failure(
                    terms_url=document.terms_url,
                    status=failure_status,
                    failure_reason=f"{type(exc).__name__}: {exc}",
                    collector_version=COLLECTOR_VERSION,
                )
            results.append(result)
    finally:
        await store.close()
    return {"collector_version": COLLECTOR_VERSION, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="显式采集固定官方来源条款证据")
    parser.add_argument("--provider", choices=("all", "cninfo", "gdelt"), default="all")
    parser.add_argument("--timeout-seconds", type=int, default=15)
    parser.add_argument("--env-file", default=str(ROOT / ".env.host"))
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 60:
        parser.error("--timeout-seconds 必须在 1 到 60 之间")
    try:
        load_env_file(Path(args.env_file))
        result = asyncio.run(collect(args.provider, args.timeout_seconds))
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(f"来源条款证据采集失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
