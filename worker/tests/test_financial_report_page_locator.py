import unittest
from uuid import UUID

from services.financial_report_page_locator import locate_metadata, normalize_page_text


class FinancialReportPageLocatorTests(unittest.TestCase):
    def test_normalize_page_text_is_deterministic(self):
        self.assertEqual(normalize_page_text("Ａ股\r\n  单位： 人民币元  \n\n"), "A股\n单位: 人民币元")

    def test_unique_candidates_are_located(self):
        pages = [
            {
                "page_evidence_id": UUID("00000000-0000-0000-0000-000000000001"),
                "page_number": 1,
                "extraction_status": "text_observed",
                "text": "报告期末为2025年12月31日。单位:人民币元。审计意见。合并资产负债表",
            }
        ]
        locations = locate_metadata(pages)
        self.assertEqual({row["field_name"] for row in locations}, {
            "report_period_end", "statement_currency_unit",
            "audit_opinion_section", "statement_scope_heading",
        })
        self.assertTrue(all(row["status"] == "located" for row in locations))

    def test_multiple_and_missing_candidates_are_not_inferred(self):
        pages = [
            {
                "page_evidence_id": UUID("00000000-0000-0000-0000-000000000001"),
                "page_number": 1,
                "extraction_status": "text_observed",
                "text": "2025年12月31日 2024年12月31日",
            }
        ]
        locations = locate_metadata(pages)
        period_rows = [row for row in locations if row["field_name"] == "report_period_end"]
        self.assertTrue(all(row["status"] == "ambiguous" for row in period_rows))
        unresolved = [row for row in locations if row["status"] == "unresolved"]
        self.assertEqual(len(unresolved), 3)


if __name__ == "__main__":
    unittest.main()
