from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data.free_observation_ledger import FreeObservationLedger, FreeObservationLedgerError


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreeObservationLedgerError("FREE_OBSERVATION_LEDGER_INPUT_INVALID", f"无法读取 JSON 文件：{path}") from exc
    if not isinstance(value, dict):
        raise FreeObservationLedgerError("FREE_OBSERVATION_LEDGER_INPUT_INVALID", f"JSON 根对象必须为对象：{path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply explicit free-observation candidates to a local virtual account.")
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--artifact", action="append", required=True, type=Path)
    parser.add_argument("--prior-ledger", type=Path)
    parser.add_argument("--initial-cash")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--confirm-free-observation", action="store_true")
    args = parser.parse_args()
    if not args.confirm_free_observation:
        print("必须显式传入 --confirm-free-observation；本命令不会创建订单、成交或正式账务。", file=sys.stderr)
        return 2
    if os.environ.get("APP_ENV", "development").strip().lower() == "production":
        print("免费观测账本仅允许 local_development，拒绝 production。", file=sys.stderr)
        return 2
    if bool(args.prior_ledger) == bool(args.initial_cash):
        print("首次运行必须提供 --initial-cash，续跑必须提供 --prior-ledger，二者只能提供其一。", file=sys.stderr)
        return 2
    try:
        initial_cash = Decimal(args.initial_cash) if args.initial_cash else None
    except InvalidOperation:
        print("--initial-cash 必须为十进制金额。", file=sys.stderr)
        return 2
    try:
        result = FreeObservationLedger.apply(
            candidate_document=_read_json(args.candidate),
            artifacts=[_read_json(path) for path in args.artifact],
            initial_cash=initial_cash,
            prior_ledger=_read_json(args.prior_ledger) if args.prior_ledger else None,
        )
        serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
            stream.write("\n")
        print(serialized)
        return 0
    except FileExistsError:
        print(f"观测账本文件已存在，拒绝覆盖：{args.output}", file=sys.stderr)
        return 2
    except FreeObservationLedgerError as exc:
        print(f"免费观测账本失败（fail-closed，{exc.code}）：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
