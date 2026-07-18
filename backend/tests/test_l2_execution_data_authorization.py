import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "l2-data-authorization-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.core.auth import Principal
from app.risk.checker import RiskCheckReport
from app.trade.base_trader import OrderRequest
from app.trade.execution_authorization import (
    EXECUTION_AUTHORIZATION_POLICY_VERSION,
    ExecutionAuthorizationError,
    ExecutionAuthorizationService,
    ORDER_ACTION,
    order_payload_hash,
)
from app.trade.order_manager import OrderManager
from app.trade.preflight import OrderPreflightResult


REQUESTER_ID = "00000000-0000-0000-0000-000000000001"
APPROVER_ID = "00000000-0000-0000-0000-000000000002"
APPROVAL_ID = "00000000-0000-0000-0000-000000000010"


class _Result:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row

    def one(self):
        if self.row is None:
            raise AssertionError("expected a row")
        return self.row


class _ApprovalDb:
    def __init__(self, approval_row=None):
        self.approval_row = approval_row
        self.calls = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "INSERT INTO trade.execution_approvals" in sql:
            return _Result(
                {
                    "approval_id": APPROVAL_ID,
                    "status": "requested",
                    "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
                }
            )
        if "FROM trade.execution_approvals" in sql:
            return _Result(self.approval_row)
        if "UPDATE trade.execution_approvals" in sql:
            return _Result({"approval_id": APPROVAL_ID})
        if "INSERT INTO trade.execution_approval_events" in sql:
            return _Result()
        raise AssertionError(sql)


class _ReadinessDb:
    def __init__(self, valid):
        self.valid = valid
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _Result({"valid": self.valid})


class _AuthorizationService(ExecutionAuthorizationService):
    def __init__(self, valid):
        self.valid = valid
        self.validation_calls = []

    async def _has_execution_data_authorization(self, _db, authorization_ref, stock_code):
        self.validation_calls.append((authorization_ref, stock_code))
        return self.valid


class L2ExecutionDataAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.requester = Principal(
            principal_id=REQUESTER_ID,
            display_name="requester",
            principal_type="human",
            role="trader",
            scopes=frozenset(),
            source="credential",
        )
        self.payload = {
            "stock_code": "600000",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": 100,
            "limit_price": 10,
            "mode": "paper",
        }

    def _approved_row(self, *, policy_version=EXECUTION_AUTHORIZATION_POLICY_VERSION):
        return {
            "action_type": ORDER_ACTION,
            "mode": "paper",
            "payload_hash": order_payload_hash(self.payload),
            "requester_principal_id": REQUESTER_ID,
            "approver_principal_id": APPROVER_ID,
            "data_authorization_ref": "review-1",
            "policy_version": policy_version,
            "status": "approved",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        }

    def test_request_rejects_unverifiable_data_reference_before_persisting_approval(self):
        db = _ApprovalDb()
        service = _AuthorizationService(False)

        with self.assertRaises(ExecutionAuthorizationError) as raised:
            asyncio.run(
                service.request_order_approval(
                    db,
                    principal=self.requester,
                    payload=self.payload,
                    data_authorization_ref="review-1",
                    expires_in_seconds=900,
                )
            )

        self.assertEqual(raised.exception.code, "DATA_AUTHORIZATION_INVALID")
        self.assertEqual(service.validation_calls, [("review-1", "600000")])
        self.assertFalse(any("INSERT INTO trade.execution_approvals" in sql for sql, _ in db.calls))

    def test_request_and_consume_revalidate_server_data_reference(self):
        request_db = _ApprovalDb()
        request_service = _AuthorizationService(True)

        requested = asyncio.run(
            request_service.request_order_approval(
                request_db,
                principal=self.requester,
                payload=self.payload,
                data_authorization_ref="review-1",
                expires_in_seconds=900,
            )
        )

        insert_params = next(
            params
            for sql, params in request_db.calls
            if "INSERT INTO trade.execution_approvals" in sql
        )
        self.assertEqual(requested["approval_id"], APPROVAL_ID)
        self.assertEqual(insert_params["data_authorization_ref"], "review-1")
        self.assertEqual(
            insert_params["policy_version"], EXECUTION_AUTHORIZATION_POLICY_VERSION
        )

        invalid_db = _ApprovalDb(self._approved_row())
        invalid_service = _AuthorizationService(False)
        with self.assertRaises(ExecutionAuthorizationError) as raised:
            asyncio.run(
                invalid_service.consume_order_approval(
                    invalid_db,
                    approval_id=APPROVAL_ID,
                    principal=self.requester,
                    payload=self.payload,
                    intent_id="intent-1",
                )
            )
        self.assertEqual(raised.exception.code, "DATA_AUTHORIZATION_INVALID")
        self.assertFalse(any("UPDATE trade.execution_approvals" in sql for sql, _ in invalid_db.calls))

        consume_db = _ApprovalDb(self._approved_row())
        consume_service = _AuthorizationService(True)
        asyncio.run(
            consume_service.consume_order_approval(
                consume_db,
                approval_id=APPROVAL_ID,
                principal=self.requester,
                payload=self.payload,
                intent_id="intent-1",
            )
        )
        self.assertTrue(any("UPDATE trade.execution_approvals" in sql for sql, _ in consume_db.calls))

    def test_previous_policy_version_is_rejected_before_data_reference_use(self):
        db = _ApprovalDb(self._approved_row(policy_version="execution-authorization-v2"))
        service = _AuthorizationService(True)

        with self.assertRaises(ExecutionAuthorizationError) as raised:
            asyncio.run(
                service.consume_order_approval(
                    db,
                    approval_id=APPROVAL_ID,
                    principal=self.requester,
                    payload=self.payload,
                    intent_id="intent-1",
                )
            )

        self.assertEqual(raised.exception.code, "APPROVAL_POLICY_VERSION_MISMATCH")
        self.assertEqual(service.validation_calls, [])

    def test_reference_query_requires_current_complete_execution_review(self):
        db = _ReadinessDb(True)

        valid = asyncio.run(
            ExecutionAuthorizationService()._has_execution_data_authorization(
                db, "review-1", "600000"
            )
        )

        self.assertTrue(valid)
        sql, params = db.calls[0]
        self.assertIn("market.research_readiness_reviews", sql)
        self.assertIn("NOT EXISTS", sql)
        self.assertEqual(params["stock_code"], "600000.SH")
        self.assertEqual(params["research_use_scope"], "execution_reference")
        self.assertEqual(params["requirement_profile"], "EXECUTION_REFERENCE_V1")
        self.assertEqual(
            json.loads(params["required_fields"]),
            ["quote_time", "price_applicability", "explicit_authorization", "execution_gate"],
        )
        self.assertGreaterEqual(params["freshness_seconds"], 60)

    def test_order_manager_blocks_before_trader_when_reference_revalidation_fails(self):
        class Preflight:
            @staticmethod
            def _allowed():
                return OrderPreflightResult("test", RiskCheckReport(passed=True))

            def check_input(self, _request):
                return self._allowed()

            def check_execution_gate(self, _request, _mode):
                return self._allowed()

            async def check_fuse(self, _mode):
                return self._allowed()

            async def check_risk(self, _request, _mode, *, record_risk_events):
                if not record_risk_events:
                    raise AssertionError("order risk check must record audit events")
                return self._allowed()

        class Authorization:
            def __init__(self):
                self.marked = []

            async def create_order_intent(self, *_args, **_kwargs):
                return "intent-1", False, "pending"

            async def consume_order_approval(self, *_args, **_kwargs):
                raise ExecutionAuthorizationError(
                    "DATA_AUTHORIZATION_INVALID", "执行数据授权引用不可验证", 403
                )

            async def mark_intent(self, _db, intent_id, status):
                self.marked.append((intent_id, status))

        trader = SimpleNamespace(submit_order=AsyncMock())
        manager = OrderManager(object(), object(), object(), {"simulation": trader})
        manager.preflight = Preflight()
        manager._find_by_idempotency = AsyncMock(return_value=None)
        authorization = Authorization()
        manager.execution_authorization = authorization
        request = OrderRequest(
            stock_code="600000",
            side="BUY",
            order_type="LIMIT",
            quantity=100,
            limit_price=10,
            trigger_source="manual_order",
            principal=self.requester,
            principal_id=REQUESTER_ID,
            client_intent_key="intent-key-0001",
            approval_id=APPROVAL_ID,
            data_certification_status="server_authorization_required",
        )

        result = asyncio.run(manager.create_order(request, "simulation"))

        self.assertEqual(result["error_code"], "DATA_AUTHORIZATION_INVALID")
        self.assertEqual(authorization.marked, [("intent-1", "rejected")])
        trader.submit_order.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
