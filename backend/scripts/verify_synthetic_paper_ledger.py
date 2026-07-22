from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("APP_ENV", "local_development")
os.environ.setdefault("SECRET_KEY", "synthetic-paper-test-only-secret-key-32chars")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://synthetic-test-only@localhost/unused")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/unused")

from app.trade.synthetic_test_ledger import (  # noqa: E402
    SYNTHETIC_PAPER_RULESET_VERSION,
    TEST_ACTOR_ID,
    SyntheticPaperError,
    SyntheticPaperLedger,
)


def _run_once() -> dict[str, object]:
    reference = SyntheticPaperLedger.build_execution_reference()
    ledger = SyntheticPaperLedger()
    filled = ledger.submit_order(
        actor_id=TEST_ACTOR_ID,
        idempotency_key="test:p4-filled-buy-v1",
        stock_code="TEST:000001",
        side="BUY",
        quantity=100,
        limit_price=Decimal("11.00"),
        reference=reference,
        reason="test-only 成交与费用验证",
    )
    ledger.approve_order(
        order_id=filled.order_id,
        actor_id=TEST_ACTOR_ID,
        approved=True,
        reason="test-only 本地单人例外审批",
        single_operator_exception=True,
    )
    if not ledger.execute_order(order_id=filled.order_id, reference=reference):
        raise RuntimeError("预期 synthetic 成交订单未成交")
    ledger.release_t1(order_id=filled.order_id, actor_id=TEST_ACTOR_ID)

    unfilled = ledger.submit_order(
        actor_id=TEST_ACTOR_ID,
        idempotency_key="test:p4-unfilled-buy-v1",
        stock_code="TEST:000001",
        side="BUY",
        quantity=100,
        limit_price=Decimal("10.00"),
        reference=reference,
        reason="test-only 未成交与撤单验证",
    )
    ledger.approve_order(
        order_id=unfilled.order_id,
        actor_id=TEST_ACTOR_ID,
        approved=True,
        reason="test-only 本地单人例外审批",
        single_operator_exception=True,
    )
    if ledger.execute_order(order_id=unfilled.order_id, reference=reference):
        raise RuntimeError("预期 synthetic 未成交订单错误成交")
    ledger.cancel_order(
        order_id=unfilled.order_id,
        actor_id=TEST_ACTOR_ID,
        reason="test-only 未成交撤单并释放冻结资金",
    )
    report = ledger.audit_report()
    report["execution_reference_hash"] = reference.reference_hash
    return report


def build_verification_report() -> dict[str, object]:
    runs = tuple(_run_once() for _ in range(3))
    first = runs[0]
    if any(run["audit_report_hash"] != first["audit_report_hash"] for run in runs):
        raise RuntimeError("三次相同 synthetic/test-only 账务运行的审计 Hash 不一致")
    if any(run["execution_reference_hash"] != first["execution_reference_hash"] for run in runs):
        raise RuntimeError("三次相同 synthetic/test-only 运行的执行参考 Hash 不一致")
    if any(any(value != 0 for value in run["formal_write_counts"].values()) for run in runs):
        raise RuntimeError("检测到非 synthetic 正式链路写入")
    if any(any(run["release_locks"].values()) for run in runs):
        raise RuntimeError("检测到发布或交易锁被打开")
    if any(run["profile"] != {"status": "draft", "runner_usable": False} for run in runs):
        raise RuntimeError("正式 P3 Profile 状态发生变化")
    invalid_reference = replace(
        SyntheticPaperLedger.build_execution_reference(), fixture_kind="replay"
    )
    try:
        SyntheticPaperLedger().submit_order(
            actor_id=TEST_ACTOR_ID,
            idempotency_key="test:p4-invalid-input-v1",
            stock_code="TEST:000001",
            side="BUY",
            quantity=100,
            limit_price=Decimal("11.00"),
            reference=invalid_reference,
            reason="test-only 非 synthetic 输入拒绝验证",
        )
    except SyntheticPaperError as exc:
        if exc.code != "P4_TEST_ONLY_INPUT_REQUIRED":
            raise RuntimeError(f"非 synthetic 输入返回错误码 {exc.code}") from exc
    else:
        raise RuntimeError("非 synthetic 输入未被拒绝")
    return {
        "fixture_kind": first["fixture_kind"],
        "ruleset_version": SYNTHETIC_PAPER_RULESET_VERSION,
        "deterministic": True,
        "run_hashes": [run["audit_report_hash"] for run in runs],
        "execution_reference_hash": first["execution_reference_hash"],
        "event_count": first["event_count"],
        "snapshot_hash": first["snapshot_hash"],
        "reconciliation": first["reconciliation"],
        "formal_write_counts": first["formal_write_counts"],
        "release_locks": first["release_locks"],
        "profile": first["profile"],
        "formal_p3_replay": first["formal_p3_replay"],
        "formal_p4": first["formal_p4"],
        "non_synthetic_rejected": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="运行显式 synthetic/test-only P4 账务工程验证。")
    parser.add_argument(
        "--confirm-test-only",
        action="store_true",
        help="确认仅运行本地 test-only 账务验证，不启动正式 Paper。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="可选的新 JSON 审计文件；已有文件拒绝覆盖。",
    )
    args = parser.parse_args()
    if not args.confirm_test_only:
        print("必须显式传入 --confirm-test-only；本命令不会启动正式 Paper。", file=sys.stderr)
        return 2
    try:
        serialized = json.dumps(build_verification_report(), ensure_ascii=False, indent=2, sort_keys=True)
        if args.output is not None:
            try:
                with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(serialized)
                    stream.write("\n")
            except FileExistsError:
                print(f"审计文件已存在，拒绝覆盖：{args.output}", file=sys.stderr)
                return 2
        print(serialized)
        return 0
    except Exception as exc:
        print(f"synthetic/test-only P4 账务验证失败（fail-closed）：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
