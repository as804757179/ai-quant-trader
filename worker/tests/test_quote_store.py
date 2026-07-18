import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from services.quote_store import QuoteStore


class QuoteStoreTests(unittest.TestCase):
    def test_success_is_not_visible_before_rows_are_written(self):
        store = QuoteStore.__new__(QuoteStore)
        store._insert_batch = AsyncMock()
        store._insert_quotes_and_provenance = AsyncMock(return_value=["000001.SZ"])
        store._finalize_batch = AsyncMock()

        result = asyncio.run(
            store.persist_batch(
                ["000001.SZ"],
                {"000001.SZ": {"stock_code": "000001.SZ", "price": 10.0}},
                {
                    "provider": "tencent",
                    "source": "tencent_qt_gtimg_l1",
                    "fetch_endpoint": "https://qt.gtimg.cn/q",
                    "fallback_used": False,
                    "status": "success",
                    "collector_version": "test-collector",
                    "normalizer_version": "test-normalizer",
                },
                datetime.now(timezone.utc),
            )
        )

        inserted_batch = store._insert_batch.await_args.args[0]
        self.assertEqual(inserted_batch["status"], "running")
        self.assertEqual(result["status"], "success")
        store._finalize_batch.assert_awaited_once()
        self.assertEqual(store._finalize_batch.await_args.args[1], "success")


if __name__ == "__main__":
    unittest.main()
