import asyncio
from types import SimpleNamespace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.data.client import DataFetchResult
from app.data.service import DataService
from app.api.stock import set_data_status_headers
from fastapi import Response


class _Cache:
    async def get(self, _key):
        return None

    async def set(self, _key, _value, ttl=None):
        return None

    async def mget(self, _keys):
        return []


class _UnavailableClient:
    async def fetch_kline_result(self, *_args):
        return DataFetchResult(
            status="timeout",
            error_code="UPSTREAM_TIMEOUT",
            retryable=True,
            provenance={"service": "a-stock-data"},
        )


class DataServiceFailClosedTests(unittest.TestCase):
    def test_kline_timeout_does_not_use_untracked_sina_fallback(self):
        async def run():
            service = DataService()
            service.cache = _Cache()
            service.client = _UnavailableClient()
            rows = await service.get_kline("600000", period="1min", limit=20)
            self.assertEqual(rows, [])

        asyncio.run(run())

    def test_kline_rejects_unsupported_adjustment_before_fetch(self):
        async def run():
            service = DataService()
            service.cache = _Cache()
            service.client = _UnavailableClient()
            with self.assertRaisesRegex(ValueError, "unsupported kline adjustment"):
                await service.get_kline("600000", period="1d", limit=20, adj="hfq")

        asyncio.run(run())

    def test_data_service_no_longer_imports_sina_fallback(self):
        source = (Path(__file__).parents[1] / "app" / "data" / "service.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("fetch_sina_kline", source)
        self.assertIn("fetch_kline_result", source)

    def test_data_status_headers_preserve_safe_typed_outcome(self):
        response = Response()
        set_data_status_headers(
            response,
            SimpleNamespace(
                status="fetch_failed",
                error_code="UPSTREAM_TIMEOUT",
                retryable=True,
                provenance={
                    "source": "backend_memory_cache\r\nignored",
                    "quality_status": "observed",
                    "usage_status": "display_only",
                },
            ),
        )
        self.assertEqual(response.headers["X-Data-Status"], "fetch_failed")
        self.assertEqual(response.headers["X-Data-Error-Code"], "UPSTREAM_TIMEOUT")
        self.assertEqual(response.headers["X-Data-Retryable"], "true")
        self.assertEqual(response.headers["X-Data-Source"], "backend_memory_cacheignored")


if __name__ == "__main__":
    unittest.main()
