import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

import httpx

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "l2-execution-safety-contract-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("WS_REDIS_ENABLED", "false")

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "worker"))

from pydantic import ValidationError

from app.api import risk as risk_api
from app.core.auth import Principal, set_auth_service_for_testing
from app.main import app
from app.schemas.trade import OrderCreateRequest
from app.schemas.trade import PreTradeCheckRequest
from app.risk.checker import PreTradeRiskChecker, RiskCheckReport
from app.core.auth import route_access
from app.trade.execution_authorization import canonical_order_payload, order_payload_hash
from app.trade.preflight import OrderPreflightResult
from worker.services.backend_client import DirectBackendClient, HttpBackendClient


class L2ExecutionSafetyContracts(unittest.TestCase):
    def test_order_request_rejects_legacy_client_authorization_fields(self):
        with self.assertRaises(ValidationError):
            OrderCreateRequest(
                stock_code="600000",
                side="BUY",
                quantity=100,
                client_intent_key="intent-0001",
                approval_id="fake",
            )

    def test_order_request_requires_intent_key(self):
        with self.assertRaises(ValidationError):
            OrderCreateRequest(stock_code="600000", side="BUY", quantity=100)

    def test_precheck_does_not_create_an_execution_intent(self):
        request = PreTradeCheckRequest(stock_code="600000", side="BUY", quantity=100)
        self.assertEqual(request.mode, "simulation")

    def test_precheck_http_path_uses_non_mutating_shared_preflight(self):
        calls = []

        class AuthService:
            async def authenticate(self, *_args, **_kwargs):
                return Principal(
                    principal_id="00000000-0000-0000-0000-000000000001",
                    display_name="worker",
                    principal_type="service",
                    role="service_worker",
                    scopes=frozenset({"risk:precheck"}),
                    source="credential",
                )

            def validate_csrf(self, *_args, **_kwargs):
                return None

        @asynccontextmanager
        async def fake_db():
            yield object()

        async def fake_check(_self, request, mode, *, record_risk_events):
            calls.append((request, mode, record_risk_events))
            return OrderPreflightResult(
                "execution_gate",
                RiskCheckReport(
                    passed=False,
                    blocked_by=["TRADING_EXECUTION_DISABLED"],
                ),
            )

        async def scenario():
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.post(
                    "/api/v1/risk/pre-check",
                    headers={"Authorization": "Bearer test"},
                    json={
                        "stock_code": "600000",
                        "side": "BUY",
                        "quantity": 100,
                        "limit_price": 10,
                        "mode": "simulation",
                    },
                )

        set_auth_service_for_testing(AuthService())
        try:
            with patch.object(risk_api, "get_db", fake_db), patch.object(
                risk_api.OrderPreflight, "check", fake_check
            ):
                response = asyncio.run(scenario())
        finally:
            set_auth_service_for_testing(None)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertFalse(body["data"]["passed"])
        self.assertEqual(body["data"]["blocked_by"], ["TRADING_EXECUTION_DISABLED"])
        self.assertEqual(len(calls), 1)
        dry_run_request, mode, record_risk_events = calls[0]
        self.assertEqual(mode, "simulation")
        self.assertEqual(dry_run_request.caller, "risk_precheck")
        self.assertEqual(dry_run_request.data_certification_status, "unknown")
        self.assertFalse(record_risk_events)

    def test_worker_submission_is_disabled(self):
        async def run():
            for client in (HttpBackendClient(), DirectBackendClient()):
                with self.assertRaisesRegex(RuntimeError, "worker_order_submission_disabled"):
                    await client.submit_order({})
                await client.close()

        asyncio.run(run())

    def test_risk_rules_database_failure_blocks(self):
        async def run():
            db = type("Db", (), {"execute": AsyncMock(side_effect=RuntimeError("db down"))})()
            report = await PreTradeRiskChecker(db, object()).check(
                {"stock_code": "600000", "quantity": 100, "side": "BUY"},
                "simulation",
            )
            self.assertFalse(report.passed)
            self.assertEqual(report.blocked_by, ["RISK_RULES_UNAVAILABLE"])

        asyncio.run(run())

    def test_order_hash_excludes_client_authorization_fields(self):
        payload = {
            "stock_code": "600000",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": 100,
            "limit_price": 10.123,
            "mode": "paper",
            "execution_authorization_id": "must-not-change-hash",
            "client_intent_key": "intent-0001",
            "live_confirm": "must-not-change-hash",
        }
        canonical = canonical_order_payload(payload)
        self.assertEqual(canonical["limit_price"], 10.12)
        self.assertNotIn("execution_authorization_id", canonical)
        self.assertEqual(order_payload_hash(payload), order_payload_hash(canonical))

    def test_approval_routes_have_separate_scopes(self):
        self.assertEqual(
            route_access("POST", "/api/v1/trade/approvals").scope,
            "trade:approval.request",
        )
        self.assertEqual(
            route_access("POST", "/api/v1/trade/approvals/abc/approve").scope,
            "trade:approval.approve",
        )

    def test_order_manager_authorizes_before_trader_and_outboxes_before_submit(self):
        source = (Path(__file__).parents[1] / "app" / "trade" / "order_manager.py").read_text(
            encoding="utf-8"
        )
        self.assertLess(source.index("consume_order_approval"), source.index("trader.submit_order"))
        self.assertLess(source.index("prepare_broker_outbox"), source.index("trader.submit_order"))

    def test_migration_is_append_only(self):
        path = Path(__file__).parents[1] / "alembic" / "versions" / "025_execution_approval_intent_safety.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn('revision = "025"', text)
        self.assertIn('down_revision = "024"', text)
        self.assertIn("raise RuntimeError", text)
        self.assertIn("trade.execution_approvals", text)
        self.assertIn("trade.order_intents", text)
        self.assertIn("trg_execution_approval_events_immutable", text)


if __name__ == "__main__":
    unittest.main()
