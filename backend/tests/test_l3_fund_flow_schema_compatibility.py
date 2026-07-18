import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FundFlowSchemaCompatibilityTests(unittest.TestCase):
    def test_compatibility_migration_restores_all_legacy_columns(self):
        migration = (
            ROOT / "alembic" / "versions" / "037_fund_flow_column_compatibility.py"
        ).read_text(encoding="utf-8")
        for column in (
            "super_large_in",
            "large_in",
            "medium_in",
            "small_in",
            "north_net_in",
        ):
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column}", migration)

    def test_data_service_reads_the_compatibility_columns(self):
        source = (ROOT / "app" / "data" / "service.py").read_text(encoding="utf-8")
        for column in (
            "super_large_in",
            "large_in",
            "medium_in",
            "small_in",
            "main_net_in",
            "north_net_in",
        ):
            self.assertIn(column, source)


if __name__ == "__main__":
    unittest.main()
