import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from services.research_source_usage_store import (
    DECISION_STATUSES,
    SOURCE_TERMS_DOCUMENTS,
    USAGE_SCOPES,
    get_source_terms_document,
)


class ResearchSourceUsageEvidenceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migration = (
            ROOT / "backend/alembic/versions/022_research_source_usage_evidence.py"
        ).read_text(encoding="utf-8")
        cls.adr = (
            ROOT / "docs/adr/ADR-018-research-source-usage-evidence-governance.md"
        ).read_text(encoding="utf-8")

    def test_migration_extends_current_head_and_creates_audit_tables(self):
        self.assertIn('down_revision = "021"', self.migration)
        self.assertIn("market.research_source_terms_evidence", self.migration)
        self.assertIn("market.research_source_usage_reviews", self.migration)
        self.assertIn("ON DELETE RESTRICT", self.migration)

    def test_sources_and_official_urls_are_fixed(self):
        self.assertIn("cninfo_listed_company_disclosure", self.migration)
        self.assertIn("gdelt_article_list_rss", self.migration)
        self.assertIn("https://www.cninfo.com.cn/new/index.htm", self.migration)
        self.assertIn("disclosure%2Flist%2Fnotice", self.migration)
        self.assertIn("https://www.gdeltproject.org/about.html", self.migration)
        self.assertIn("announcing-the-gdelt-article-list-rss-feed", self.migration)

    def test_reviews_cannot_approve_or_expand_usage_scope(self):
        self.assertIn("decision_status IN ('review_required', 'rejected')", self.migration)
        self.assertNotIn("decision_status IN ('review_required', 'rejected', 'approved')", self.migration)
        for usage_scope in (
            "manual_observation",
            "automated_fetch",
            "local_storage",
            "derived_research",
            "redistribution",
        ):
            self.assertIn(usage_scope, self.migration)
        self.assertIn("identity_assurance = 'unverified'", self.migration)

    def test_both_tables_are_database_immutable(self):
        self.assertIn("BEFORE UPDATE OR DELETE ON market.research_source_terms_evidence", self.migration)
        self.assertIn("BEFORE UPDATE OR DELETE ON market.research_source_usage_reviews", self.migration)
        self.assertIn("append-only", self.migration)

    def test_adr_keeps_readiness_and_third_party_content_closed(self):
        self.assertIn("不实现 `approved`", self.adr)
        self.assertIn("不授予 Research Readiness", self.adr)
        self.assertIn("不覆盖第三方新闻正文、图片、附件", self.adr)
        self.assertIn("不移除 `PROVIDER_USAGE_PERMISSION_UNAPPROVED`", self.adr)

    def test_store_uses_only_confirmed_documents_and_pre_review_values(self):
        self.assertEqual(len(SOURCE_TERMS_DOCUMENTS), 4)
        self.assertEqual(DECISION_STATUSES, {"review_required", "rejected"})
        self.assertEqual(
            USAGE_SCOPES,
            {
                "manual_observation",
                "automated_fetch",
                "local_storage",
                "derived_research",
                "redistribution",
            },
        )
        with self.assertRaisesRegex(ValueError, "固定官方清单"):
            get_source_terms_document("https://example.com/terms")

    def test_scripts_are_explicit_and_have_no_approval_path(self):
        collector = (
            ROOT / "scripts/collect_research_source_terms_evidence.py"
        ).read_text(encoding="utf-8")
        reviewer = (
            ROOT / "scripts/append_research_source_usage_review.py"
        ).read_text(encoding="utf-8")
        self.assertIn('choices=("all", "cninfo", "gdelt")', collector)
        self.assertNotIn("schedule", collector.lower())
        self.assertIn('choices=("review_required", "rejected")', reviewer)
        self.assertNotIn('"approved"', reviewer)

    def test_read_only_api_and_precheck_reference_cannot_grant_permission(self):
        api_source = (ROOT / "backend/app/api/research.py").read_text(
            encoding="utf-8"
        )
        readiness_source = (
            ROOT / "backend/app/data/research_evidence_readiness.py"
        ).read_text(encoding="utf-8")
        self.assertIn('@router.get("/source-usage-evidence")', api_source)
        self.assertNotIn('@router.post("/source-usage-evidence")', api_source)
        self.assertIn('"authorization_granted": False', api_source)
        self.assertIn('"source_usage_evidence": self.source_usage_evidence', readiness_source)
        self.assertIn('source_usage_evidence.get("authorization_granted") is True', readiness_source)


if __name__ == "__main__":
    unittest.main()
