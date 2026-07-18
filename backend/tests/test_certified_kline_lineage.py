import asyncio
import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("SECRET_KEY", "contract-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.api import data  # noqa: E402
from app.core.auth import route_access  # noqa: E402
from app.data.certified_kline_repository import CertifiedKlineRepository  # noqa: E402


class _Result:
    def __init__(self, *, one=None, rows=None):
        self._one = one
        self._rows = rows or []

    def mappings(self):
        return self

    def one(self):
        return self._one

    def all(self):
        return self._rows


class _Db:
    def __init__(self, results):
        self._results = list(results)
        self.sql = []
        self.params = []

    async def execute(self, statement, params):
        self.sql.append(str(statement))
        self.params.append(params)
        return self._results.pop(0)


class _DbContext:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class CertifiedKlineLineageTests(unittest.TestCase):
    def test_repository_uses_certified_store_and_stable_server_page(self):
        db = _Db(
            [
                _Result(
                    one={
                        "total": 2,
                        "stock_count": 1,
                        "date_from": date(2026, 1, 1),
                        "date_to": date(2026, 1, 2),
                        "providers": ["provider-a"],
                    }
                ),
                _Result(
                    rows=[
                        {
                            "stock_code": "000001.SZ",
                            "trading_date": date(2026, 1, 2),
                            "period": "1d",
                            "adjustment": "raw",
                            "provider": "provider-a",
                            "source": "source-a",
                            "batch_id": "batch-1",
                            "raw_hash": "a" * 64,
                            "quality_status": "pass",
                            "certification_status": "certified",
                            "certification_time": None,
                            "importer_version": "v1",
                            "normalizer_version": "v1",
                            "schema_version": "v1",
                            "research_readiness_status": "review_required",
                            "review_reason": "not granted",
                        }
                    ]
                ),
            ]
        )
        repository = CertifiedKlineRepository()
        with patch("app.data.certified_kline_repository.get_db", return_value=_DbContext(db)):
            payload = asyncio.run(
                repository.list_lineage(
                    stock_code="000001",
                    date_from=None,
                    date_to=None,
                    period="1d",
                    adjustment="raw",
                    batch_id=None,
                    page=1,
                    page_size=1,
                )
            )

        self.assertEqual(payload["total"], 2)
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["items"][0]["stock_code"], "000001.SZ")
        self.assertIn("market.certified_klines", db.sql[0])
        self.assertNotIn("market.klines", db.sql[0])
        self.assertIn("quality_status = 'pass'", db.sql[1])
        self.assertIn("certification_status = 'certified'", db.sql[1])
        self.assertIn("ORDER BY trading_date DESC, stock_code, batch_id", db.sql[1])
        self.assertIn("LIMIT :limit OFFSET :offset", db.sql[1])

    def test_route_is_read_only_and_does_not_grant_readiness(self):
        route = next(item for item in data.router.routes if item.path == "/certified-klines")
        self.assertEqual(route.methods, {"GET"})
        self.assertEqual(route_access("GET", "/api/v1/data/certified-klines").scope, "market:read")
        lineage = {
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 50,
            "has_more": False,
            "summary": {"stock_count": 0, "date_from": None, "date_to": None, "providers": []},
        }
        repository = AsyncMock()
        repository.list_lineage.return_value = lineage
        with patch("app.api.data.CertifiedKlineRepository", return_value=repository):
            response = asyncio.run(
                data.list_certified_klines(
                    stock_code=None,
                    date_from=None,
                    date_to=None,
                    period="1d",
                    adjustment="raw",
                    batch_id=None,
                    page=1,
                    page_size=50,
                )
            )

        self.assertEqual(response.data["certification_scope"], "certified_store_observation")
        self.assertEqual(response.data["research_readiness"], "not_granted")
        self.assertFalse(response.data["tradable"])
        self.assertFalse(response.data["order_created"])


if __name__ == "__main__":
    unittest.main()
