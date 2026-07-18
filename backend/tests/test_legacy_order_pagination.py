import asyncio
import os
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "contract-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.services.trade_service import TradeService


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value

    def fetchall(self):
        return [SimpleNamespace(_mapping=row) for row in self.value]


class _Db:
    def __init__(self, *results):
        self.results = list(results)
        self.sql = []
        self.params = []

    async def execute(self, statement, params=None):
        self.sql.append(str(statement))
        self.params.append(params or {})
        return _Result(self.results.pop(0))


class _DbContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return False


class LegacyOrderPaginationTests(unittest.TestCase):
    def test_orders_return_real_total_stable_page_and_has_more(self):
        db = _Db(
            3,
            [
                {
                    "id": "order-2",
                    "created_at": datetime(2026, 7, 17, 8, 0, tzinfo=UTC),
                    "filled_at": None,
                }
            ],
        )
        with patch("app.services.trade_service.get_db", return_value=_DbContext(db)):
            payload = asyncio.run(
                TradeService().list_orders(
                    mode="simulation",
                    status=None,
                    days=7,
                    page=2,
                    page_size=1,
                )
            )

        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["page"], 2)
        self.assertEqual(payload["page_size"], 1)
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["items"][0]["id"], "order-2")
        self.assertEqual(payload["items"][0]["created_at"], "2026-07-17T08:00:00+00:00")
        self.assertEqual(db.params[1]["offset"], 1)
        self.assertIn("COUNT(*) AS total", db.sql[0])
        self.assertIn("ORDER BY created_at DESC, id DESC", db.sql[1])
        self.assertIn("LIMIT :limit OFFSET :offset", db.sql[1])
        self.assertFalse(
            any(
                operation in statement.upper()
                for statement in db.sql
                for operation in ("INSERT", "UPDATE", "DELETE")
            )
        )


if __name__ == "__main__":
    unittest.main()
