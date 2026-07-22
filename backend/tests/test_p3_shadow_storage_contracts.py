import os
import sys
import unittest
from pathlib import Path
from uuid import uuid4


os.environ.setdefault("SECRET_KEY", "p3-shadow-storage-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.shadow.contracts import ShadowContractError  # noqa: E402
from app.shadow.repository import ShadowRepository  # noqa: E402


class _Result:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class _Db:
    def __init__(self, existing=None):
        self.existing = existing
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), dict(params or {})))
        if "ON CONFLICT (idempotency_key)" in str(statement):
            return _Result(None)
        return _Result(self.existing)


class P3ShadowStorageContractTests(unittest.TestCase):
    def test_migration_has_shadow_only_zero_side_effect_constraints(self):
        source = (REPO_ROOT / "backend/alembic/versions/042_p3_shadow_run_infrastructure.py").read_text(encoding="utf-8")
        self.assertIn("CREATE SCHEMA IF NOT EXISTS shadow", source)
        self.assertIn("CHECK (tradable = FALSE)", source)
        self.assertIn("CHECK (order_created = FALSE)", source)
        self.assertIn("CHECK (order_count = 0)", source)
        self.assertIn("idempotency_key VARCHAR(128) NOT NULL UNIQUE", source)
        self.assertIn("decision_dedup_key CHAR(64) NOT NULL UNIQUE", source)

    def test_repository_reuses_same_idempotency_input(self):
        existing = {"run_id": str(uuid4()), "request_hash": "a" * 64, "status": "created"}
        db = _Db(existing)
        result, created = __import__("asyncio").run(
            ShadowRepository().create_run(
                db,
                run_id=uuid4(),
                idempotency_key="test:run-key",
                request_hash="a" * 64,
                payload={},
            )
        )
        self.assertFalse(created)
        self.assertEqual(result["run_id"], existing["run_id"])

    def test_repository_rejects_changed_idempotency_input(self):
        db = _Db({"run_id": str(uuid4()), "request_hash": "a" * 64, "status": "created"})
        with self.assertRaises(ShadowContractError) as raised:
            __import__("asyncio").run(
                ShadowRepository().create_run(
                    db,
                    run_id=uuid4(),
                    idempotency_key="test:run-key",
                    request_hash="b" * 64,
                    payload={},
                )
            )
        self.assertEqual(raised.exception.code, "P3_IDEMPOTENCY_PAYLOAD_CONFLICT")


if __name__ == "__main__":
    unittest.main()
