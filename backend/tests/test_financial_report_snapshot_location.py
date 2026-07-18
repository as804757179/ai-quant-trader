import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class FinancialReportSnapshotLocationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migration = (
            ROOT
            / "backend/alembic/versions/023_financial_report_snapshot_location.py"
        ).read_text(encoding="utf-8")
        cls.adr = (
            ROOT
            / "docs/adr/ADR-019-financial-report-snapshot-and-page-location.md"
        ).read_text(encoding="utf-8")

    def test_migration_extends_022_and_uses_append_only_sidecars(self):
        self.assertIn('down_revision = "022"', self.migration)
        for table in (
            "market.research_financial_report_snapshots",
            "market.research_financial_report_parse_runs",
            "market.research_financial_report_page_evidence",
            "market.research_financial_metadata_locations",
        ):
            self.assertIn(table, self.migration)
        self.assertEqual(self.migration.count("BEFORE UPDATE OR DELETE ON"), 4)

    def test_snapshot_scope_and_hash_binding_are_database_enforced(self):
        self.assertIn("cef779d8-96d7-4a01-8ae3-2b9a023447e0", self.migration)
        self.assertIn("522d97a3-ff33-4001-81da-6575cd4ad8e3", self.migration)
        self.assertIn("expected hash or bytes do not match", self.migration)
        self.assertIn("acquisition_method = 'explicit_refetch'", self.migration)
        self.assertIn("review_scope IS DISTINCT FROM 'local_storage'", self.migration)
        self.assertIn("review_scope IS DISTINCT FROM 'derived_research'", self.migration)

    def test_parser_and_location_values_are_fixed(self):
        self.assertIn("parser_name = 'pypdf'", self.migration)
        self.assertIn("parser_version = '3.17.4'", self.migration)
        for field_name in (
            "report_period_end",
            "statement_currency_unit",
            "audit_opinion_section",
            "statement_scope_heading",
        ):
            self.assertIn(field_name, self.migration)
        self.assertNotIn("financial_reports SET", self.migration)

    def test_adr_keeps_permission_readiness_and_numeric_facts_closed(self):
        self.assertIn("不能被解释为 Provider 许可批准", self.adr)
        self.assertIn("不解析财务数值", self.adr)
        self.assertIn("不授予 Research Readiness", self.adr)
        self.assertIn("不修改 `market.research_financial_report_details`", self.adr)

    def test_snapshot_script_has_fixed_ids_and_no_schedule_or_url_input(self):
        source = (
            ROOT / "scripts/snapshot_financial_report_evidence.py"
        ).read_text(encoding="utf-8")
        self.assertIn("cef779d8-96d7-4a01-8ae3-2b9a023447e0", source)
        self.assertIn("522d97a3-ff33-4001-81da-6575cd4ad8e3", source)
        self.assertNotIn('add_argument("--url"', source)
        self.assertNotIn("schedule", source.lower())

    def test_page_locator_and_read_only_api_sidecar_are_fixed_scope(self):
        locator = (
            ROOT / "scripts/locate_financial_report_metadata.py"
        ).read_text(encoding="utf-8")
        api = (ROOT / "backend/app/api/research.py").read_text(encoding="utf-8")
        self.assertIn("cef779d8-96d7-4a01-8ae3-2b9a023447e0", locator)
        self.assertIn("522d97a3-ff33-4001-81da-6575cd4ad8e3", locator)
        self.assertNotIn('add_argument("--url"', locator)
        self.assertIn("financial_report_snapshot_location", api)
        self.assertIn("research_financial_metadata_locations", api)
        self.assertIn('"research_readiness": "not_granted"', api)


if __name__ == "__main__":
    unittest.main()
