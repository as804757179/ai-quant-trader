import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AnnouncementSchemaCompatibilityTests(unittest.TestCase):
    def test_compatibility_migration_restores_legacy_read_columns(self):
        migration = (
            ROOT / "alembic" / "versions" / "038_announcement_compatibility_table.py"
        ).read_text(encoding="utf-8")
        for column in (
            "stock_code",
            "title",
            "category",
            "publish_time",
            "content_url",
        ):
            self.assertIn(column, migration)

    def test_legacy_news_route_does_not_merge_remote_news_provider(self):
        source = (ROOT / "app" / "data" / "service.py").read_text(encoding="utf-8")
        start = source.index("async def get_news_result")
        end = source.index("def _validate_quote", start)
        news_source = source[start:end]
        self.assertIn("fundamental.announcements", news_source)
        self.assertNotIn("fetch_news_result", news_source)


if __name__ == "__main__":
    unittest.main()
