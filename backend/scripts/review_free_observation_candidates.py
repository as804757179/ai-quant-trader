from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data.free_observation_review import FreeObservationReview, FreeObservationReviewError


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreeObservationReviewError("FREE_OBSERVATION_REVIEW_INVALID", f"无法读取 JSON 文件：{path}") from exc
    if not isinstance(value, dict):
        raise FreeObservationReviewError("FREE_OBSERVATION_REVIEW_INVALID", f"JSON 根对象必须为对象：{path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Review explicit free-observation candidates against later observation files.")
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--artifact", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--confirm-free-observation", action="store_true")
    args = parser.parse_args()
    if not args.confirm_free_observation:
        print("必须显式传入 --confirm-free-observation；本命令不会启动正式 P3/P4 或交易。", file=sys.stderr)
        return 2
    if os.environ.get("APP_ENV", "development").strip().lower() == "production":
        print("免费观测复盘仅允许 local_development，拒绝 production。", file=sys.stderr)
        return 2
    try:
        report = FreeObservationReview.evaluate(
            candidate_document=_read_json(args.candidate),
            artifacts=[_read_json(path) for path in args.artifact],
        )
        serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
            stream.write("\n")
        print(serialized)
        return 0
    except FileExistsError:
        print(f"复盘文件已存在，拒绝覆盖：{args.output}", file=sys.stderr)
        return 2
    except FreeObservationReviewError as exc:
        print(f"免费观测复盘失败（fail-closed，{exc.code}）：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
