import os
import sys
import unittest
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "p3-lineage-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.data.certified_kline_lineage import certified_kline_row_hash


class CertifiedLineageTests(unittest.TestCase):
    def test_row_hash_is_stable_and_protected_fields_change_it(self):
        row = {"stock_code":"000001.SZ","period":"1d","trading_date":"2026-01-02","adjustment":"raw","open":Decimal("10.0000"),"high":Decimal("11.0000"),"low":Decimal("9.0000"),"close":Decimal("10.5000"),"volume":1,"amount":Decimal("10.00"),"provider":"test","source":"fixture","batch_id":"batch","raw_hash":"a" * 64}
        self.assertEqual(certified_kline_row_hash(row), certified_kline_row_hash(dict(row)))
        changed = dict(row, close=Decimal("10.6000"))
        self.assertNotEqual(certified_kline_row_hash(row), certified_kline_row_hash(changed))


if __name__ == "__main__":
    unittest.main()
