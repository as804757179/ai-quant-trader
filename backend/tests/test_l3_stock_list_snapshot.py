import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class StockListSnapshotContractTests(unittest.TestCase):
    def test_stock_list_exposes_storage_coverage_without_claiming_certification(self):
        source = (ROOT / "backend" / "app" / "services" / "stock_service.py").read_text(
            encoding="utf-8"
        )
        for fragment in (
            "MIN(updated_at) OVER() AS _coverage_started_at",
            "MAX(updated_at) OVER() AS _coverage_updated_at",
            '"source": "fundamental.stocks"',
            '"coverage_count": total',
            '"status": "available" if total else "unavailable"',
        ):
            self.assertIn(fragment, source)
        self.assertNotIn('"certified": True', source)


if __name__ == "__main__":
    unittest.main()
