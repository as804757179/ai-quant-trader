import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "contract-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.api import stock


ROOT = Path(__file__).resolve().parents[2]


class _BatchResult:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def all(self):
        return self.value if isinstance(self.value, list) else []

    def scalar(self):
        return self.value


class _BatchDb:
    def __init__(self, *results):
        self.results = list(results)
        self.sql = []
        self.params = []

    async def execute(self, statement, params=None):
        self.sql.append(str(statement))
        self.params.append(params or {})
        return _BatchResult(self.results.pop(0))


class _BatchDbContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return False


class RealtimeQuoteProvenanceContractTests(unittest.TestCase):
    def test_quote_provenance_routes_are_read_only(self):
        expected = ("/market/status", "/market/batches")
        for path in expected:
            route = next(item for item in stock.router.routes if item.path == path)
            self.assertEqual(route.methods, {"GET"})

    def test_migration_rejects_unknown_synthetic_and_fallback(self):
        migration = (ROOT / "backend/alembic/versions/015_realtime_quote_provenance.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("market.quote_batches", migration)
        self.assertIn("market.quote_provenance", migration)
        self.assertIn("provider NOT IN ('unknown', 'synthetic')", migration)
        self.assertIn("fallback_used = FALSE", migration)

    def test_quote_batch_lifecycle_has_explicit_running_state(self):
        migration = (ROOT / "backend/alembic/versions/017_quote_batch_running_status.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("'running'", migration)
        self.assertIn("quote_batches_status_check", migration)

    def test_quote_batches_use_stable_server_pagination_and_batch_fallback(self):
        db = _BatchDb(
            3,
            [
                {
                    "batch_id": "batch-2",
                    "provider": "tencent",
                    "fallback_used": False,
                }
            ],
        )
        with patch("app.api.stock.get_db", return_value=_BatchDbContext(db)):
            response = asyncio.run(
                stock.get_market_quote_batches(limit=1, page=2, page_size=None)
            )

        payload = response.data
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["page"], 2)
        self.assertEqual(payload["page_size"], 1)
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["items"][0]["fallback_used"], False)
        self.assertEqual(payload["source_version"], "market-quote-batches-v2")
        self.assertEqual(db.params[1], {"limit": 1, "offset": 1})
        self.assertIn("COUNT(*) FROM market.quote_batches", db.sql[0])
        self.assertIn("BOOL_OR(provenance.fallback_used)", db.sql[1])
        self.assertIn("ORDER BY batch.received_at DESC, batch.batch_id DESC", db.sql[1])
        self.assertIn("OFFSET :offset", db.sql[1])
        self.assertFalse(
            any(
                operation in statement.upper()
                for statement in db.sql
                for operation in ("INSERT", "UPDATE", "DELETE")
            )
        )

    def test_worker_uses_fixed_provider_batch_path_without_single_quote_fallback(self):
        sync_source = (ROOT / "worker/services/quote_sync.py").read_text(encoding="utf-8")
        self.assertIn("fetch_quotes_with_provenance", sync_source)
        self.assertIn("QuoteStore", sync_source)
        self.assertNotIn("self.data_client.fetch_quote(", sync_source)


if __name__ == "__main__":
    unittest.main()
