import asyncio
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "l2-intent-idempotency-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.core.auth import Principal
from app.trade.execution_authorization import (
    ExecutionAuthorizationError,
    ExecutionAuthorizationService,
    order_payload_hash,
)
from app.trade.idempotency import build_idempotency_key


PRINCIPAL_ID = "00000000-0000-0000-0000-000000000001"


class _Result:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class _IntentDb:
    def __init__(self, existing=None):
        self.existing = existing
        self.calls = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "pg_advisory_xact_lock" in sql:
            return _Result()
        if "FROM trade.order_intents" in sql and "SELECT intent_id" in sql:
            return _Result(self.existing)
        if "INSERT INTO trade.order_intents" in sql:
            return _Result({"intent_id": "intent-new", "status": "pending"})
        raise AssertionError(sql)


class L2OrderIntentIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.principal = Principal(
            principal_id=PRINCIPAL_ID,
            display_name="trader",
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

    def test_expired_key_creates_new_immutable_intent_generation(self):
        db = _IntentDb(
            {
                "intent_id": "intent-old",
                "payload_hash": "a" * 64,
                "status": "rejected",
                "intent_generation": 1,
                "active": False,
            }
        )

        result = asyncio.run(
            ExecutionAuthorizationService().create_order_intent(
                db,
                principal=self.principal,
                client_intent_key="intent-key-0001",
                payload=self.payload,
            )
        )

        self.assertEqual(result, ("intent-new", False, "pending"))
        self.assertIn("pg_advisory_xact_lock", db.calls[0][0])
        insert_params = next(
            params for sql, params in db.calls if "INSERT INTO trade.order_intents" in sql
        )
        self.assertEqual(insert_params["intent_generation"], 2)
        self.assertEqual(insert_params["payload_hash"], order_payload_hash(self.payload))

    def test_active_key_returns_existing_intent_or_rejects_changed_payload(self):
        existing = {
            "intent_id": "intent-current",
            "payload_hash": order_payload_hash(self.payload),
            "status": "submitted",
            "intent_generation": 3,
            "active": True,
        }
        db = _IntentDb(existing)

        result = asyncio.run(
            ExecutionAuthorizationService().create_order_intent(
                db,
                principal=self.principal,
                client_intent_key="intent-key-0001",
                payload=self.payload,
            )
        )

        self.assertEqual(result, ("intent-current", True, "submitted"))
        self.assertFalse(any("INSERT INTO trade.order_intents" in sql for sql, _ in db.calls))

        changed_payload = {**self.payload, "quantity": 200}
        with self.assertRaises(ExecutionAuthorizationError) as raised:
            asyncio.run(
                ExecutionAuthorizationService().create_order_intent(
                    _IntentDb(existing),
                    principal=self.principal,
                    client_intent_key="intent-key-0001",
                    payload=changed_payload,
                )
            )
        self.assertEqual(raised.exception.code, "IDEMPOTENCY_KEY_PAYLOAD_CONFLICT")

    def test_order_idempotency_key_is_scoped_to_intent(self):
        common = {
            "mode": "paper",
            "signal_id": None,
            "stock_code": "600000",
            "side": "BUY",
            "quantity": 100,
            "order_type": "LIMIT",
            "limit_price": 10,
            "principal_id": PRINCIPAL_ID,
            "client_intent_key": "intent-key-0001",
        }
        self.assertNotEqual(
            build_idempotency_key(**common, intent_id="intent-old"),
            build_idempotency_key(**common, intent_id="intent-new"),
        )

    def test_migration_preserves_records_and_replaces_permanent_key_constraint(self):
        migration = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "030_order_intent_idempotency_window.py"
        ).read_text(encoding="utf-8")

        self.assertIn('revision = "030"', migration)
        self.assertIn('down_revision = "029"', migration)
        self.assertIn("ADD COLUMN intent_generation", migration)
        self.assertIn("DROP CONSTRAINT order_intents_principal_id_client_intent_key_key", migration)
        self.assertIn("UNIQUE (principal_id, client_intent_key, intent_generation)", migration)
        self.assertIn("raise RuntimeError", migration)


if __name__ == "__main__":
    unittest.main()
