import asyncio
import os
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("SECRET_KEY", "l5-risk-precheck-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.risk.checker import PreTradeRiskChecker, RiskCheckReport  # noqa: E402
from app.trade.base_trader import OrderRequest  # noqa: E402
from app.trade.execution_gate import ExecutionDecision  # noqa: E402
from app.trade.order_manager import OrderManager  # noqa: E402
from app.trade.preflight import (  # noqa: E402
    OrderPreflight,
    build_dry_run_order_request,
)


def run(coro):
    return asyncio.run(coro)


class _Monitor:
    async def get_portfolio_snapshot(self, _mode):
        return {
            "total_assets": 100_000,
            "total_market_value": 0,
            "daily_pnl_pct": 0,
            "drawdown_from_peak": 0,
            "positions": {},
            "valuation_status": "cash_only",
        }


class _ObservedQuoteChecker(PreTradeRiskChecker):
    def __init__(self, *, observed_quote):
        super().__init__(None, _Monitor())
        self.observed_quote = observed_quote
        self.logged_events = 0
        self.remote_quote_calls = 0

    async def _ensure_thresholds(self):
        self._rules_loaded = True
        self.thresholds = {
            "MAX_SINGLE_POSITION": 1.0,
            "WARN_SINGLE_POSITION": 1.0,
            "MAX_TOTAL_POSITION": 1.0,
            "MAX_DAILY_LOSS": 1.0,
            "MAX_DRAWDOWN": 1.0,
            "MAX_ORDER_FREQ": 100,
            "MIN_DAILY_AMOUNT": 1.0,
            "MAX_SECTOR_CONCENTRATION": 1.0,
        }

    async def _get_stock(self, _code):
        return {
            "is_st": True,
            "list_date": (date.today() - timedelta(days=90)).isoformat(),
            "sector": "test",
        }

    async def _get_observed_quote(self, _code):
        if isinstance(self.observed_quote, Exception):
            raise self.observed_quote
        return self.observed_quote

    async def _get_today_quote(self, _code):
        self.remote_quote_calls += 1
        raise AssertionError("dry-run must not fetch a remote quote")

    async def _get_today_order_count(self, _mode):
        return 0

    async def _log_risk_event(self, _check, _order_request, _mode):
        self.logged_events += 1


class _AllowedGate:
    def __init__(self):
        self.calls = 0

    def evaluate(self, _request, _mode):
        self.calls += 1
        return ExecutionDecision(True)


class _BlockingGate:
    def __init__(self):
        self.calls = 0

    def evaluate(self, _request, _mode):
        self.calls += 1
        return ExecutionDecision(False, "TEST_GATE_BLOCK")


class _Fuse:
    def __init__(self, *, fused=False, error=None):
        self.fused = fused
        self.error = error
        self.calls = 0

    async def is_fused(self, _mode):
        self.calls += 1
        if self.error:
            raise self.error
        return self.fused


class _UnavailableRisk:
    async def check(self, *_args, **_kwargs):
        raise RuntimeError("risk data unavailable")


class _IntentAuthorization:
    def __init__(self):
        self.marked = []
        self.created = 0

    async def create_order_intent(self, *_args, **_kwargs):
        self.created += 1
        return "intent-1", False, "created"

    async def mark_intent(self, _db, intent_id, status):
        self.marked.append((intent_id, status))


class L5RiskPrecheckDryRunTests(unittest.TestCase):
    def test_dry_run_never_logs_risk_events_or_fetches_remote_quotes(self):
        checker = _ObservedQuoteChecker(observed_quote={"price": 10, "amount": 1000})

        report = run(
            checker.check(
                {
                    "stock_code": "600000",
                    "side": "BUY",
                    "quantity": 100,
                    "limit_price": 10,
                },
                "simulation",
                record_events=False,
            )
        )

        self.assertFalse(report.passed)
        self.assertIn("BLOCK_ST", report.blocked_by)
        self.assertEqual(checker.logged_events, 0)
        self.assertEqual(checker.remote_quote_calls, 0)

        invalid_price_checker = _ObservedQuoteChecker(
            observed_quote={"price": 10, "amount": 1000}
        )
        invalid_price_report = run(
            invalid_price_checker.check(
                {
                    "stock_code": "600000",
                    "side": "BUY",
                    "quantity": 100,
                    "limit_price": 0,
                },
                "simulation",
                record_events=False,
            )
        )
        self.assertEqual(invalid_price_report.blocked_by, ["INVALID_PRICE"])
        self.assertEqual(invalid_price_checker.logged_events, 0)

    def test_missing_observed_quote_blocks_without_data_service(self):
        checker = _ObservedQuoteChecker(observed_quote=None)
        preflight = OrderPreflight(checker, _Fuse(), _AllowedGate())

        result = run(
            preflight.check(
                build_dry_run_order_request(
                    {
                        "stock_code": "600000",
                        "side": "BUY",
                        "quantity": 100,
                        "limit_price": 10,
                    },
                    "simulation",
                ),
                "simulation",
                record_risk_events=False,
            )
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.report.blocked_by, ["OBSERVED_QUOTE_UNAVAILABLE"])
        self.assertEqual(checker.remote_quote_calls, 0)

        unavailable_checker = _ObservedQuoteChecker(observed_quote=RuntimeError("db down"))
        unavailable_result = run(
            OrderPreflight(unavailable_checker, _Fuse(), _AllowedGate()).check(
                build_dry_run_order_request(
                    {
                        "stock_code": "600000",
                        "side": "BUY",
                        "quantity": 100,
                        "limit_price": 10,
                    },
                    "simulation",
                ),
                "simulation",
                record_risk_events=False,
            )
        )
        self.assertEqual(unavailable_result.report.blocked_by, ["RISK_STATE_UNAVAILABLE"])
        self.assertEqual(unavailable_checker.remote_quote_calls, 0)

    def test_fuse_or_risk_state_uncertainty_blocks(self):
        request = build_dry_run_order_request(
            {
                "stock_code": "600000",
                "side": "BUY",
                "quantity": 100,
                "limit_price": 10,
            },
            "simulation",
        )
        fused = _Fuse(fused=True)
        fuse_result = run(
            OrderPreflight(_UnavailableRisk(), fused, _AllowedGate()).check(
                request,
                "simulation",
                record_risk_events=False,
            )
        )
        risk_result = run(
            OrderPreflight(_UnavailableRisk(), _Fuse(), _AllowedGate()).check(
                request,
                "simulation",
                record_risk_events=False,
            )
        )
        fuse_error_result = run(
            OrderPreflight(_UnavailableRisk(), _Fuse(error=RuntimeError("redis down")), _AllowedGate()).check(
                request,
                "simulation",
                record_risk_events=False,
            )
        )

        self.assertEqual(fuse_result.report.blocked_by, ["FUSE_BLOCKED"])
        self.assertEqual(risk_result.report.blocked_by, ["RISK_STATE_UNAVAILABLE"])
        self.assertEqual(fuse_error_result.report.blocked_by, ["FUSE_STATE_UNAVAILABLE"])

    def test_order_manager_uses_shared_preflight_execution_gate(self):
        gate = _BlockingGate()
        authorization = _IntentAuthorization()
        trader = SimpleNamespace(submit_order=AsyncMock())
        manager = OrderManager(
            db=object(),
            risk_checker=_UnavailableRisk(),
            fuse_manager=_Fuse(),
            traders={"simulation": trader},
            execution_gate=gate,
        )
        manager.execution_authorization = authorization
        request = OrderRequest(
            stock_code="600000",
            side="BUY",
            order_type="LIMIT",
            quantity=200,
            limit_price=10,
            trigger_source="manual_order",
            principal=object(),
            principal_id="principal-1",
            client_intent_key="intent-key-1",
        )

        result = run(manager.create_order(request, "simulation"))

        self.assertIsInstance(manager.preflight, OrderPreflight)
        self.assertEqual(result["error_code"], "ORDER_REJECTED_BY_EXECUTION_GATE")
        self.assertEqual(gate.calls, 1)
        self.assertEqual(authorization.marked, [("intent-1", "rejected")])
        trader.submit_order.assert_not_awaited()

    def test_input_rules_reject_before_an_execution_intent(self):
        gate = _AllowedGate()
        authorization = _IntentAuthorization()
        manager = OrderManager(
            db=object(),
            risk_checker=_UnavailableRisk(),
            fuse_manager=_Fuse(),
            traders={},
            execution_gate=gate,
        )
        manager.execution_authorization = authorization
        request = OrderRequest(
            stock_code="688001",
            side="BUY",
            order_type="LIMIT",
            quantity=200,
            limit_price=float("nan"),
            trigger_source="manual_order",
            principal=object(),
            principal_id="principal-1",
            client_intent_key="intent-key-1",
        )

        result = run(manager.create_order(request, "simulation"))

        self.assertEqual(result["error_code"], "ORDER_INPUT_REJECTED")
        self.assertEqual(authorization.created, 0)
        self.assertEqual(gate.calls, 0)

    def test_dry_run_builder_does_not_coerce_malformed_quantity(self):
        request = build_dry_run_order_request(
            {
                "stock_code": "600000",
                "side": "BUY",
                "quantity": "100",
                "limit_price": 10,
            },
            "simulation",
        )

        result = OrderPreflight.check_input(request)

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "INVALID_QUANTITY")

    def test_http_and_direct_precheck_paths_use_dry_run_preflight(self):
        backend_root = Path(__file__).parents[1]
        risk_api = (backend_root / "app" / "api" / "risk.py").read_text(encoding="utf-8")
        worker_client = (
            backend_root.parents[0] / "worker" / "services" / "backend_client.py"
        ).read_text(encoding="utf-8")

        self.assertIn("preflight.check(", risk_api)
        self.assertIn("record_risk_events=False", risk_api)
        self.assertIn("OrderPreflight.check_input", risk_api)
        self.assertIn("preflight.check(", worker_client)
        self.assertIn("record_risk_events=False", worker_client)


if __name__ == "__main__":
    unittest.main()
