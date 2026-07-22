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

from app.data.free_observation_daily_report import FreeObservationDailyReport, FreeObservationDailyReportError
from app.data.free_observation_dual_ma import FreeObservationDualMaEvaluator, FreeObservationEvaluationError
from app.data.free_observation_ledger import FreeObservationLedger, FreeObservationLedgerError


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 JSON 文件：{path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON 根对象必须为对象：{path}")
    return value


def _write_new(path: Path, value: dict[str, object]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one explicit local free-observation candidate, ledger, and report cycle.")
    parser.add_argument("--artifact", action="append", required=True, type=Path)
    parser.add_argument("--strategy-snapshot", required=True, type=Path)
    parser.add_argument("--prior-ledger", type=Path)
    parser.add_argument("--initial-cash")
    parser.add_argument("--candidate-output", required=True, type=Path)
    parser.add_argument("--ledger-output", required=True, type=Path)
    parser.add_argument("--report-output", required=True, type=Path)
    parser.add_argument("--confirm-free-observation", action="store_true")
    args = parser.parse_args()
    if not args.confirm_free_observation:
        print("必须显式传入 --confirm-free-observation；本命令不会访问 Provider 或创建正式交易事实。", file=sys.stderr)
        return 2
    if os.environ.get("APP_ENV", "development").strip().lower() == "production":
        print("免费观测循环仅允许 local_development，拒绝 production。", file=sys.stderr)
        return 2
    if bool(args.prior_ledger) == bool(args.initial_cash):
        print("首次运行必须提供 --initial-cash，续跑必须提供 --prior-ledger，二者只能提供其一。", file=sys.stderr)
        return 2
    outputs = (args.candidate_output, args.ledger_output, args.report_output)
    if len(set(outputs)) != len(outputs) or any(path.exists() for path in outputs):
        print("输出路径必须互不相同且均不存在，拒绝覆盖。", file=sys.stderr)
        return 2
    try:
        initial_cash = Decimal(args.initial_cash) if args.initial_cash else None
    except InvalidOperation:
        print("--initial-cash 必须为十进制金额。", file=sys.stderr)
        return 2
    try:
        artifacts = [_read_json(path) for path in args.artifact]
        candidate = FreeObservationDualMaEvaluator.evaluate(
            artifacts=artifacts,
            strategy_snapshot=_read_json(args.strategy_snapshot),
        ).as_dict()
        ledger = FreeObservationLedger.apply(
            candidate_document=candidate,
            artifacts=artifacts,
            initial_cash=initial_cash,
            prior_ledger=_read_json(args.prior_ledger) if args.prior_ledger else None,
        )
        report = FreeObservationDailyReport.build(candidate_document=candidate, ledger_document=ledger)
        _write_new(args.candidate_output, candidate)
        _write_new(args.ledger_output, ledger)
        _write_new(args.report_output, report)
        print(json.dumps({"candidate_result_hash": candidate["result_hash"], "ledger_hash": ledger["ledger_hash"], "report_hash": report["report_hash"]}, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, FreeObservationEvaluationError, FreeObservationLedgerError, FreeObservationDailyReportError) as exc:
        code = getattr(exc, "code", "FREE_OBSERVATION_CYCLE_INPUT_INVALID")
        print(f"免费观测循环失败（fail-closed，{code}）：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
