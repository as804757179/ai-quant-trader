import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from services.quote_sync import QuoteSyncService


class FakeDataClient:
    def __init__(self):
        self.requests: list[list[str]] = []

    async def fetch_quotes_with_provenance(self, codes):
        self.requests.append(list(codes))
        quotes = {
            code: {"stock_code": code, "price": 10.0, "high": 10.1, "low": 9.9}
            for code in codes
        }
        return quotes, {
            "provider": "tencent",
            "source": "tencent_qt_gtimg_l1",
            "fetch_endpoint": "https://qt.gtimg.cn/q",
            "fallback_used": False,
            "status": "success",
        }

    async def close(self):
        return None


class FakeQuoteStore:
    def __init__(self):
        self.batches = []

    async def persist_batch(self, requested_codes, quotes, metadata, started_at):
        self.batches.append((list(requested_codes), metadata))
        return {
            "batch_id": f"batch-{len(self.batches)}",
            "status": "success",
            "accepted_codes": list(quotes),
            "rejected_symbols": 0,
            "failure_reason": None,
        }

    async def close(self):
        return None


class FakeCache:
    def __init__(self):
        self.published = []

    async def set(self, key, value, ttl):
        self.published.append(("set", key, value["provenance"]["provider"], ttl))

    async def publish(self, channel, payload):
        self.published.append(("publish", channel, payload["provenance"]["fallback_used"]))

    async def close(self):
        return None


class QuoteSyncTests(unittest.TestCase):
    def test_sync_uses_fixed_provider_batches_and_persists_provenance(self):
        data_client = FakeDataClient()
        quote_store = FakeQuoteStore()
        cache = FakeCache()
        service = QuoteSyncService(
            data_client=data_client,
            quote_store=quote_store,
            cache=cache,
            stock_limit=5,
            batch_size=2,
        )

        async def run():
            with patch(
                "services.quote_sync.get_active_stock_codes",
                AsyncMock(return_value=["000001", "000002", "000003", "000004", "000005"]),
            ):
                return await service.sync_all()

        result = asyncio.run(run())

        self.assertEqual(result["synced"], 5)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["batches"], 3)
        self.assertEqual(data_client.requests, [["000001", "000002"], ["000003", "000004"], ["000005"]])
        self.assertEqual(len(quote_store.batches), 3)
        for _, metadata in quote_store.batches:
            self.assertEqual(metadata["provider"], "tencent")
            self.assertFalse(metadata["fallback_used"])
        self.assertTrue(cache.published)


if __name__ == "__main__":
    unittest.main()
