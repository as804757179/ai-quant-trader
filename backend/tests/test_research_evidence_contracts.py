import os
import unittest
from pathlib import Path


os.environ.setdefault("SECRET_KEY", "contract-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.api import research
from app.core.auth import route_access


ROOT = Path(__file__).resolve().parents[2]


class ResearchEvidenceContractTests(unittest.TestCase):
    def test_research_evidence_routes_are_read_only(self):
        for path in ("/evidence", "/evidence/batches", "/evidence/{evidence_id}"):
            route = next(item for item in research.router.routes if item.path == path)
            self.assertEqual(route.methods, {"GET"})
        self.assertEqual(
            route_access("GET", "/api/v1/research/evidence/example").scope,
            "research:read",
        )

    def test_migration_keeps_evidence_observed_only_and_calendar_sourced(self):
        migration = (
            ROOT / "backend/alembic/versions/018_research_evidence_observation.py"
        ).read_text(encoding="utf-8")
        self.assertIn("market.research_evidence_batches", migration)
        self.assertIn("market.research_evidence", migration)
        self.assertIn("provider NOT IN ('unknown', 'synthetic')", migration)
        self.assertIn("fallback_used = FALSE", migration)
        self.assertIn("review_required", migration)
        self.assertIn("SSE_2026_CALENDAR", migration)
        self.assertIn("SZSE_2026_CALENDAR", migration)
        self.assertIn("ON CONFLICT (exchange, trading_date) DO NOTHING", migration)

    def test_financial_report_details_stay_in_observation_sidecar(self):
        migration = (
            ROOT / "backend/alembic/versions/019_financial_report_evidence_details.py"
        ).read_text(encoding="utf-8")
        self.assertIn('down_revision = "018"', migration)
        self.assertIn("market.research_financial_report_details", migration)
        self.assertIn("provider_category = 'category_ndbg_szsh'", migration)
        self.assertIn("report_kind = 'annual'", migration)
        self.assertIn("report_period_end DATE", migration)
        self.assertIn("consolidation_scope IN ('unresolved'", migration)
        self.assertIn("detail_parse_status", migration)

    def test_news_details_keep_gdelt_rss_observation_semantics(self):
        migration = (
            ROOT / "backend/alembic/versions/020_news_evidence_details.py"
        ).read_text(encoding="utf-8")
        self.assertIn('down_revision = "019"', migration)
        self.assertIn("market.research_news_details", migration)
        self.assertIn("storage.googleapis.com/data.gdeltproject.org", migration)
        self.assertIn("publication_or_first_seen", migration)
        self.assertIn("title_alias_match", migration)
        self.assertIn("title_link_only", migration)
        self.assertIn("feed_window_minutes = 15", migration)
        self.assertIn("rss_item_xml_reserialized", migration)

    def test_news_manual_reviews_are_append_only_and_observation_scoped(self):
        migration = (
            ROOT / "backend/alembic/versions/021_news_evidence_manual_reviews.py"
        ).read_text(encoding="utf-8")
        source = (ROOT / "backend/app/api/research.py").read_text(encoding="utf-8")
        self.assertIn('down_revision = "020"', migration)
        self.assertIn("market.research_news_evidence_reviews", migration)
        self.assertIn("title_link_relevant", migration)
        self.assertIn("title_link_irrelevant", migration)
        self.assertIn("needs_more_evidence", migration)
        self.assertIn("idx_research_news_evidence_reviews_latest", migration)
        self.assertIn("manual_review", source)
        self.assertIn("LEFT JOIN LATERAL", source)
        self.assertIn("quality_status = 'observed'", source)
        self.assertIn("usage_status = 'review_required'", source)
        routes = [
            route
            for route in research.router.routes
            if route.path == "/evidence/{evidence_id}/reviews"
        ]
        self.assertEqual({frozenset(route.methods) for route in routes}, {frozenset({"GET"}), frozenset({"POST"})})

    def test_observation_api_does_not_grant_readiness_or_trading(self):
        source = (ROOT / "backend/app/api/research.py").read_text(encoding="utf-8")
        self.assertIn('"research_readiness": "not_granted"', source)
        self.assertIn('"observed_only": True', source)
        self.assertIn('"tradable": False', source)
        self.assertIn('"order_created": False', source)
        self.assertIn("financial_report_detail", source)
        self.assertIn("LEFT JOIN market.research_financial_report_details", source)
        self.assertIn("news_detail", source)
        self.assertIn("LEFT JOIN market.research_news_details", source)
        self.assertIn('"research_readiness": "not_granted"', source)


if __name__ == "__main__":
    unittest.main()
