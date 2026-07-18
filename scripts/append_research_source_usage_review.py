"""Explicitly append an unapproved source usage pre-review."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
POLICY_VERSION = "source-usage-pre-review-v1"


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


async def append_review(args: argparse.Namespace) -> dict[str, object]:
    from services.research_source_usage_store import ResearchSourceUsageStore

    store = ResearchSourceUsageStore()
    try:
        return await store.append_usage_review(
            terms_evidence_id=UUID(args.terms_evidence_id),
            usage_scope=args.usage_scope,
            decision_status=args.decision_status,
            reason=args.reason,
            reviewer_label=args.reviewer_label,
            policy_version=POLICY_VERSION,
        )
    finally:
        await store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="追加来源使用许可预审记录")
    parser.add_argument("--terms-evidence-id", required=True)
    parser.add_argument(
        "--usage-scope",
        required=True,
        choices=(
            "manual_observation",
            "automated_fetch",
            "local_storage",
            "derived_research",
            "redistribution",
        ),
    )
    parser.add_argument(
        "--decision-status",
        required=True,
        choices=("review_required", "rejected"),
    )
    parser.add_argument("--reason", required=True)
    parser.add_argument("--reviewer-label", required=True)
    parser.add_argument("--env-file", default=str(ROOT / ".env.host"))
    args = parser.parse_args()
    try:
        load_env_file(Path(args.env_file))
        result = asyncio.run(append_review(args))
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(f"来源使用预审追加失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
