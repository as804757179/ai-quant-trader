import asyncio
import json
import os
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
os.environ["APP_ENV"] = "development"
os.environ["SECRET_KEY"] = "l2-operation-approval-contract-test-secret"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["WS_REDIS_ENABLED"] = "false"

from pydantic import ValidationError  # noqa: E402

from app.api import trade as trade_api  # noqa: E402
from app.api.risk import FuseRecoverRequest  # noqa: E402
from app.core.auth import (  # noqa: E402
    Principal,
    ROLE_SCOPES,
    set_auth_service_for_testing,
)
from app.main import app  # noqa: E402
from app.risk.fuse import FuseManager  # noqa: E402
from app.schemas.trade import OperationApprovalRequest, OrderCancelRequest  # noqa: E402
from app.trade.execution_authorization import (  # noqa: E402
    EXECUTION_AUTHORIZATION_POLICY_VERSION,
    ExecutionAuthorizationError,
    ExecutionAuthorizationService,
    canonical_operation_payload,
    operation_payload_hash,
)


REQUESTER_ID = "00000000-0000-0000-0000-000000000001"
APPROVER_ID = "00000000-0000-0000-0000-000000000002"
APPROVAL_ID = "00000000-0000-0000-0000-000000000010"


def run(coro):
    return asyncio.run(coro)


class _Mappings:
    def __init__(self, row):
        self.row = row

    def one(self):
        if self.row is None:
            raise AssertionError("expected one row")
        return self.row

    def first(self):
        return self.row


class _Result:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return _Mappings(self.row)


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
        if "SELECT action_type" in sql:
            return _Result(self.approval_row)
        if "SET status = 'consumed'" in sql:
            return _Result({"approval_id": APPROVAL_ID})
        return _Result()


class _FuseDb:
    def __init__(self, recovered):
        self.recovered = recovered
        self.calls = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "UPDATE risk.fuse_records" in sql:
            return _Result({"id": 7} if self.recovered else None)
        return _Result()


class _Cache:
    def __init__(self):
        self.deleted = []

    async def delete_raw_strict(self, key):
        self.deleted.append(key)


class _AuthService:
    def __init__(self, principal):
        self.principal = principal

    async def authenticate(self, *_args, **_kwargs):
        return self.principal

    def validate_csrf(self, *_args, **_kwargs):
        return None


class OperationApprovalContractTests(unittest.TestCase):
    def setUp(self):
        self.requester = Principal(
            principal_id=REQUESTER_ID,
            display_name="requester",
            principal_type="human",
            role="trader",
            scopes=frozenset(),
            source="credential",
        )

    def test_operation_payloads_are_action_specific_and_stable(self):
        payload = {"order_id": " order-1 ", "mode": "PAPER"}
        canonical = canonical_operation_payload("trade.order.cancel", payload)
        self.assertEqual(canonical, {"order_id": "order-1", "mode": "paper"})
        self.assertEqual(
            operation_payload_hash("trade.order.cancel", payload),
            operation_payload_hash("trade.order.cancel", canonical),
        )
        with self.assertRaises(ExecutionAuthorizationError) as raised:
            canonical_operation_payload(
                "trade.order.cancel",
                {"order_id": "order-1", "mode": "paper", "approved_by": "forged"},
            )
        self.assertEqual(raised.exception.code, "INVALID_APPROVAL_PAYLOAD")

    def test_operation_request_and_consumption_bind_action_payload_principals_and_policy(self):
        payload = {"mode": "simulation", "force_all": False}

        async def scenario():
            service = ExecutionAuthorizationService()
            request_db = _ApprovalDb()
            requested = await service.request_operation_approval(
                request_db,
                principal=self.requester,
                action_type="trade.simulation.release_t1",
                payload=payload,
                expires_in_seconds=900,
            )
            insert_params = request_db.calls[0][1]
            self.assertEqual(insert_params["action_type"], "trade.simulation.release_t1")
            self.assertEqual(insert_params["mode"], "simulation")
            self.assertEqual(
                insert_params["policy_version"], EXECUTION_AUTHORIZATION_POLICY_VERSION
            )
            self.assertEqual(
                requested["payload_hash"],
                operation_payload_hash("trade.simulation.release_t1", payload),
            )

            approval_row = {
                "action_type": "trade.simulation.release_t1",
                "mode": "simulation",
                "payload_hash": requested["payload_hash"],
                "requester_principal_id": REQUESTER_ID,
                "approver_principal_id": APPROVER_ID,
                "policy_version": EXECUTION_AUTHORIZATION_POLICY_VERSION,
                "status": "approved",
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
            }
            consume_db = _ApprovalDb(approval_row)
            consumed = await service.consume_operation_approval(
                consume_db,
                approval_id=APPROVAL_ID,
                principal=self.requester,
                action_type="trade.simulation.release_t1",
                payload=payload,
            )
            self.assertEqual(consumed["approver_principal_id"], APPROVER_ID)
            self.assertEqual(consumed["payload"], payload)
            self.assertTrue(
                any("SET status = 'consumed'" in sql for sql, _ in consume_db.calls)
            )

        run(scenario())

    def test_operation_consumption_rejects_policy_or_payload_mismatch(self):
        payload = {"mode": "paper"}
        approval_row = {
            "action_type": "trade.reconcile",
            "mode": "paper",
            "payload_hash": operation_payload_hash("trade.reconcile", payload),
            "requester_principal_id": REQUESTER_ID,
            "approver_principal_id": APPROVER_ID,
            "policy_version": "execution-authorization-v1",
            "status": "approved",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        }

        async def scenario():
            with self.assertRaises(ExecutionAuthorizationError) as raised:
                await ExecutionAuthorizationService().consume_operation_approval(
                    _ApprovalDb(approval_row),
                    approval_id=APPROVAL_ID,
                    principal=self.requester,
                    action_type="trade.reconcile",
                    payload=payload,
                )
            self.assertEqual(raised.exception.code, "APPROVAL_POLICY_VERSION_MISMATCH")

        run(scenario())

    def test_consumed_operation_approval_is_not_reusable(self):
        payload = {"mode": "paper"}
        approval_row = {
            "action_type": "trade.reconcile",
            "mode": "paper",
            "payload_hash": operation_payload_hash("trade.reconcile", payload),
            "requester_principal_id": REQUESTER_ID,
            "approver_principal_id": APPROVER_ID,
            "policy_version": EXECUTION_AUTHORIZATION_POLICY_VERSION,
            "status": "consumed",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        }

        async def scenario():
            with self.assertRaises(ExecutionAuthorizationError) as raised:
                await ExecutionAuthorizationService().consume_operation_approval(
                    _ApprovalDb(approval_row),
                    approval_id=APPROVAL_ID,
                    principal=self.requester,
                    action_type="trade.reconcile",
                    payload=payload,
                )
            self.assertEqual(raised.exception.code, "APPROVAL_INVALID")
            self.assertEqual(raised.exception.status_code, 403)

        run(scenario())

    def test_operation_approval_rejects_non_human_principal(self):
        service_principal = Principal(
            principal_id=REQUESTER_ID,
            display_name="worker",
            principal_type="service",
            role="service_worker",
            scopes=frozenset(),
            source="credential",
        )

        async def scenario():
            with self.assertRaises(ExecutionAuthorizationError) as raised:
                await ExecutionAuthorizationService().request_operation_approval(
                    _ApprovalDb(),
                    principal=service_principal,
                    action_type="trade.reconcile",
                    payload={"mode": "paper"},
                    expires_in_seconds=900,
                )
            self.assertEqual(raised.exception.code, "HUMAN_PRINCIPAL_REQUIRED")

        run(scenario())

    def test_operation_request_models_reject_client_approval_identity(self):
        OrderCancelRequest(
            order_id="00000000-0000-0000-0000-000000000001",
            mode="paper",
            execution_authorization_id=APPROVAL_ID,
        )
        with self.assertRaises(ValidationError):
            OrderCancelRequest(order_id="00000000-0000-0000-0000-000000000001", mode="paper")
        with self.assertRaises(ValidationError):
            FuseRecoverRequest(
                mode="paper",
                fuse_record_id=7,
                execution_authorization_id=APPROVAL_ID,
                approved_by="forged",
            )
        OperationApprovalRequest(
            action_type="risk.fuse.recover",
            payload={"mode": "paper", "fuse_record_id": 7, "note": "reviewed"},
        )
        with self.assertRaises(ValidationError):
            OperationApprovalRequest(
                action_type="risk.fuse.activate",
                payload={"mode": "paper"},
            )

    def test_recovery_uses_record_id_and_persists_server_approval_audit(self):
        cache = _Cache()
        db = _FuseDb(recovered=True)
        result = run(FuseManager(db, cache).recover("paper", 7, APPROVER_ID, "reviewed"))
        self.assertTrue(result)
        self.assertEqual(cache.deleted, ["fuse:paper"])
        event_params = db.calls[1][1]
        detail = json.loads(event_params["detail"])
        self.assertEqual(detail["fuse_record_id"], 7)
        self.assertEqual(detail["approved_by"], APPROVER_ID)

        stale_cache = _Cache()
        stale_db = _FuseDb(recovered=False)
        stale_result = run(
            FuseManager(stale_db, stale_cache).recover("paper", 7, APPROVER_ID, "reviewed")
        )
        self.assertFalse(stale_result)
        self.assertEqual(stale_cache.deleted, [])
        self.assertEqual(len(stale_db.calls), 1)

    def test_roles_support_separated_operation_request_and_approval(self):
        self.assertIn("trade:approval.request", ROLE_SCOPES["risk_admin"])
        self.assertIn("trade:approval.approve", ROLE_SCOPES["risk_admin"])
        self.assertIn("trade:approval.request", ROLE_SCOPES["admin"])

    def test_routes_enforce_operation_approval_contracts_after_authentication(self):
        async def fake_db_context(db):
            @asynccontextmanager
            async def context():
                yield db

            return context

        async def send(principal, method, path, **kwargs):
            set_auth_service_for_testing(_AuthService(principal))
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.request(method, path, headers={"Authorization": "Bearer test"}, **kwargs)

        requester = Principal(
            principal_id=REQUESTER_ID,
            display_name="requester",
            principal_type="human",
            role="trader",
            scopes=frozenset({"trade:approval.request", "trade:order.cancel"}),
            source="session",
        )
        risk_admin = Principal(
            principal_id=APPROVER_ID,
            display_name="risk-admin",
            principal_type="human",
            role="risk_admin",
            scopes=frozenset({"risk:fuse.recover"}),
            source="session",
        )
        db = _ApprovalDb()

        async def scenario():
            context = await fake_db_context(db)
            with patch.object(trade_api, "get_db", context):
                approved = await send(
                    requester,
                    "POST",
                    "/api/v1/trade/approvals",
                    json={
                        "action_type": "trade.reconcile",
                        "payload": {"mode": "paper"},
                        "expires_in_seconds": 900,
                    },
                )
            self.assertEqual(approved.status_code, 200)
            self.assertTrue(approved.json()["success"])
            self.assertEqual(db.calls[0][1]["action_type"], "trade.reconcile")

            missing_approval = await send(
                requester,
                "POST",
                "/api/v1/trade/order/cancel",
                json={"order_id": "order-1", "mode": "paper"},
            )
            self.assertEqual(missing_approval.status_code, 422)

            forged_recovery = await send(
                risk_admin,
                "POST",
                "/api/v1/risk/fuse/recover",
                json={
                    "mode": "paper",
                    "fuse_record_id": 7,
                    "execution_authorization_id": APPROVAL_ID,
                    "approved_by": "forged",
                },
            )
            self.assertEqual(forged_recovery.status_code, 422)

        try:
            run(scenario())
        finally:
            set_auth_service_for_testing(None)
        release_parameters = app.openapi()["paths"]["/api/v1/trade/simulation/release-t1"]["post"]["parameters"]
        force_all = next(item for item in release_parameters if item["name"] == "force_all")
        self.assertFalse(force_all["schema"]["default"])


if __name__ == "__main__":
    unittest.main()
