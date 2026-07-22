import os
import sys
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path


os.environ.setdefault("APP_ENV", "local_development")
os.environ.setdefault("SECRET_KEY", "p4-synthetic-test-secret-key-32chars")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.shadow.contracts import RELEASE_LOCK_KEYS  # noqa: E402
from app.trade.synthetic_test_ledger import (  # noqa: E402
    INITIAL_CASH,
    TEST_ACTOR_ID,
    SyntheticPaperError,
    SyntheticPaperLedger,
)


class P4SyntheticPaperLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reference = SyntheticPaperLedger.build_execution_reference()
        self.ledger = SyntheticPaperLedger()

    def _submit(self, *, key: str, side: str = "BUY", limit: str = "11.00", quantity: int = 100):
        return self.ledger.submit_order(
            actor_id=TEST_ACTOR_ID,
            idempotency_key=key,
            stock_code="TEST:000001",
            side=side,
            quantity=quantity,
            limit_price=Decimal(limit),
            reference=self.reference,
            reason="test-only 测试订单",
        )

    def _approve(self, order_id: str) -> None:
        self.ledger.approve_order(
            order_id=order_id,
            actor_id=TEST_ACTOR_ID,
            approved=True,
            reason="test-only 本地单人例外审批",
            single_operator_exception=True,
        )

    def test_same_input_runs_three_times_with_identical_hashes(self) -> None:
        reports = []
        for _ in range(3):
            ledger = SyntheticPaperLedger()
            receipt = ledger.submit_order(
                actor_id=TEST_ACTOR_ID,
                idempotency_key="test:p4-deterministic-v1",
                stock_code="TEST:000001",
                side="BUY",
                quantity=100,
                limit_price=Decimal("11.00"),
                reference=self.reference,
                reason="test-only 确定性验证",
            )
            ledger.approve_order(
                order_id=receipt.order_id,
                actor_id=TEST_ACTOR_ID,
                approved=True,
                reason="test-only 本地单人例外审批",
                single_operator_exception=True,
            )
            self.assertTrue(ledger.execute_order(order_id=receipt.order_id, reference=self.reference))
            ledger.release_t1(order_id=receipt.order_id, actor_id=TEST_ACTOR_ID)
            reports.append(ledger.audit_report())
        self.assertEqual({report["audit_report_hash"] for report in reports}, {reports[0]["audit_report_hash"]})
        self.assertEqual({report["snapshot_hash"] for report in reports}, {reports[0]["snapshot_hash"]})

    def test_submission_and_approval_are_separate_audit_events(self) -> None:
        receipt = self._submit(key="test:p4-separation-v1")
        with self.assertRaises(SyntheticPaperError) as raised:
            self.ledger.approve_order(
                order_id=receipt.order_id,
                actor_id=TEST_ACTOR_ID,
                approved=True,
                reason="missing exception",
            )
        self.assertEqual(raised.exception.code, "P4_TEST_SEPARATION_OF_DUTIES_REQUIRED")
        self._approve(receipt.order_id)
        types = [event.event_type for event in self.ledger.events]
        self.assertEqual(types, ["ledger_initialized", "submitted", "approval", "cash_frozen"])
        self.assertTrue(self.ledger.events[2].payload["single_operator_exception"])
        self.assertFalse(self.ledger.events[2].payload["separation_of_duties"])

    def test_fill_fee_t1_and_account_rebuild(self) -> None:
        receipt = self._submit(key="test:p4-fill-v1")
        self._approve(receipt.order_id)
        self.assertTrue(self.ledger.execute_order(order_id=receipt.order_id, reference=self.reference))
        before_settlement = self.ledger.rebuild()
        self.assertEqual(before_settlement["positions"]["TEST:000001"]["available_quantity"], 0)
        self.ledger.release_t1(order_id=receipt.order_id, actor_id=TEST_ACTOR_ID)
        state = self.ledger.rebuild()
        self.assertEqual(state["cash"], Decimal("98947.95"))
        self.assertEqual(state["frozen_cash"], Decimal("0.00"))
        self.assertEqual(state["positions"]["TEST:000001"], {
            "total_quantity": 100,
            "available_quantity": 100,
            "frozen_quantity": 0,
        })
        self.assertTrue(self.ledger.reconcile_or_raise().matched)

    def test_unfilled_order_can_be_cancelled_and_releases_cash(self) -> None:
        receipt = self._submit(key="test:p4-cancel-v1", limit="10.00")
        self._approve(receipt.order_id)
        self.assertFalse(self.ledger.execute_order(order_id=receipt.order_id, reference=self.reference))
        self.assertEqual(self.ledger.rebuild()["frozen_cash"], Decimal("1001.00"))
        self.ledger.cancel_order(order_id=receipt.order_id, actor_id=TEST_ACTOR_ID, reason="test-only 撤单")
        state = self.ledger.rebuild()
        self.assertEqual(state["cash"], INITIAL_CASH)
        self.assertEqual(state["frozen_cash"], Decimal("0.00"))
        self.assertEqual(state["orders"][receipt.order_id]["status"], "cancelled")

    def test_available_cash_and_quantity_limits_fail_closed_without_partial_approval(self) -> None:
        cash_limited = self._submit(key="test:p4-cash-limit-v1", quantity=100000)
        with self.assertRaises(SyntheticPaperError) as cash_error:
            self._approve(cash_limited.order_id)
        self.assertEqual(cash_error.exception.code, "P4_TEST_INSUFFICIENT_CASH")
        self.assertEqual(self.ledger.rebuild()["orders"][cash_limited.order_id]["status"], "submitted")

        filled = self._submit(key="test:p4-qty-limit-buy-v1")
        self._approve(filled.order_id)
        self.assertTrue(self.ledger.execute_order(order_id=filled.order_id, reference=self.reference))
        sell = self._submit(key="test:p4-qty-limit-sell-v1", side="SELL", limit="10.00")
        with self.assertRaises(SyntheticPaperError) as quantity_error:
            self._approve(sell.order_id)
        self.assertEqual(quantity_error.exception.code, "P4_TEST_INSUFFICIENT_AVAILABLE_QTY")
        self.assertEqual(self.ledger.rebuild()["orders"][sell.order_id]["status"], "submitted")

    def test_idempotency_conflict_and_non_synthetic_reference_are_rejected(self) -> None:
        first = self._submit(key="test:p4-idempotency-v1")
        repeated = self._submit(key="test:p4-idempotency-v1")
        self.assertEqual(first, repeated)
        with self.assertRaises(SyntheticPaperError) as conflict:
            self._submit(key="test:p4-idempotency-v1", limit="12.00")
        self.assertEqual(conflict.exception.code, "P4_TEST_IDEMPOTENCY_CONFLICT")
        invalid_reference = replace(self.reference, fixture_kind="replay")
        with self.assertRaises(SyntheticPaperError) as invalid:
            self.ledger.submit_order(
                actor_id=TEST_ACTOR_ID,
                idempotency_key="test:p4-non-synthetic-v1",
                stock_code="TEST:000001",
                side="BUY",
                quantity=100,
                limit_price=Decimal("11.00"),
                reference=invalid_reference,
                reason="test-only 非 synthetic 输入",
            )
        self.assertEqual(invalid.exception.code, "P4_TEST_ONLY_INPUT_REQUIRED")

    def test_reconciliation_difference_is_fail_closed(self) -> None:
        expected = self.ledger.rebuild()
        expected["cash"] = Decimal("1.00")
        result = self.ledger.reconcile(expected_snapshot=expected)
        self.assertFalse(result.matched)
        self.assertEqual(result.difference, "P4_SYNTHETIC_RECONCILIATION_MISMATCH")
        with self.assertRaises(SyntheticPaperError) as raised:
            self.ledger.reconcile_or_raise(expected_snapshot=expected)
        self.assertEqual(raised.exception.code, "P4_SYNTHETIC_RECONCILIATION_MISMATCH")

    def test_formal_writes_locks_and_profile_are_unchanged(self) -> None:
        report = self.ledger.audit_report()
        self.assertEqual(report["formal_write_counts"], {
            "order": 0,
            "execution": 0,
            "capital": 0,
            "position": 0,
            "external_provider": 0,
        })
        self.assertTrue(all(report["release_locks"][key] is False for key in RELEASE_LOCK_KEYS))
        self.assertEqual(report["profile"], {"status": "draft", "runner_usable": False})
        self.assertEqual(report["formal_p3_replay"], "blocked/deferred")
        self.assertEqual(report["formal_p4"], "not_authorized")

    def test_module_has_no_database_network_or_order_service_dependencies(self) -> None:
        source = (REPO_ROOT / "backend/app/trade/synthetic_test_ledger.py").read_text(encoding="utf-8")
        for forbidden in ("sqlalchemy", "asyncpg", "httpx", "requests", "socket", "SimulationTrader", "LiveTrader"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
