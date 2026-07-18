import asyncio
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "p2-2-market-observation-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.api import market
from app.core.auth import route_access


class _Result:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def one(self):
        return self.row

    def all(self):
        return self.row if isinstance(self.row, list) else []


class _Db:
    def __init__(self, *results):
        self.results = list(results)
        self.sql = []
        self.params = []

    async def execute(self, statement, params=None):
        self.sql.append(str(statement))
        self.params.append(params or {})
        return self.results.pop(0)


class _DbContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return False


class MarketObservationContractTests(unittest.TestCase):
    def test_industry_snapshot_is_unverified_and_cannot_enter_historical_research(self):
        snapshot_updated_at = datetime(2026, 7, 18, tzinfo=timezone.utc)
        db = _Db(
            _Result({"total": 2, "stock_count": 6, "latest_snapshot_updated_at": snapshot_updated_at}),
            _Result([{"classification_name": "制造业", "stock_count": 3, "snapshot_updated_at": snapshot_updated_at}]),
        )
        with patch("app.api.market.get_db", return_value=_DbContext(db)):
            response = asyncio.run(market.list_industry_classifications(sector="制造业", page=2, page_size=1))

        payload = response.data
        item = payload["items"][0]
        self.assertEqual(item["data_semantics"], "current_snapshot")
        self.assertEqual(item["provider"], "legacy_internal")
        self.assertEqual(item["quality_status"], "unverified")
        self.assertIsNone(item["dataset_version"])
        self.assertIsNone(item["fetched_at"])
        self.assertIsNone(item["effective_from"])
        self.assertFalse(item["pit_capable"])
        self.assertFalse(item["historical_research_usable"])
        self.assertFalse(item["backtest_usable"])
        self.assertFalse(payload["observed_only"])
        self.assertEqual(payload["research_readiness"], "not_granted")
        self.assertFalse(payload["tradable"])
        self.assertFalse(payload["order_created"])
        self.assertEqual(db.params[0]["sector"], "制造业")
        self.assertIn("fundamental.stocks", db.sql[0])
        self.assertIn("ORDER BY MAX(stock.updated_at) DESC NULLS LAST, stock.sector", db.sql[1])
        self.assertFalse(any(f"{operation} " in statement.upper() for statement in db.sql for operation in ("INSERT", "UPDATE", "DELETE")))

    def test_industry_snapshot_route_requires_market_read_scope(self):
        route = next(item for item in market.router.routes if item.path == "/industry-classifications")
        self.assertEqual(route.methods, {"GET"})
        self.assertEqual(route_access("GET", "/api/v1/market/industry-classifications").scope, "market:read")

    def test_concept_boards_are_explicitly_unavailable_without_a_source_or_fallback(self):
        with patch("app.api.market.get_db", side_effect=AssertionError("concept endpoint must not query a fallback source")):
            response = asyncio.run(market.list_concept_boards(page=2, page_size=1))

        payload = response.data
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["availability_status"], "unavailable")
        self.assertEqual(payload["data_semantics"], "unavailable")
        self.assertEqual(payload["formal_model"], "market.concept_board_memberships")
        self.assertIsNone(payload["provider"])
        self.assertFalse(payload["observed_only"])
        self.assertFalse(payload["historical_research_usable"])
        self.assertFalse(payload["backtest_usable"])
        self.assertEqual(payload["research_readiness"], "not_granted")
        self.assertFalse(payload["tradable"])
        self.assertFalse(payload["order_created"])

    def test_concept_boards_route_requires_market_read_scope(self):
        route = next(item for item in market.router.routes if item.path == "/concept-boards")
        self.assertEqual(route.methods, {"GET"})
        self.assertEqual(route_access("GET", "/api/v1/market/concept-boards").scope, "market:read")

    def test_exchange_board_snapshot_is_unverified_and_cannot_enter_historical_research(self):
        snapshot_updated_at = datetime(2026, 7, 18, tzinfo=timezone.utc)
        db = _Db(
            _Result({"total": 2, "stock_count": 6, "latest_snapshot_updated_at": snapshot_updated_at}),
            _Result([{"classification_name": "主板", "stock_count": 3, "snapshot_updated_at": snapshot_updated_at}]),
        )
        with patch("app.api.market.get_db", return_value=_DbContext(db)):
            response = asyncio.run(market.list_exchange_boards(board="主板", page=2, page_size=1))

        payload = response.data
        item = payload["items"][0]
        self.assertEqual(item["classification_kind"], "exchange_board")
        self.assertEqual(item["data_semantics"], "current_snapshot")
        self.assertEqual(item["provider"], "legacy_internal")
        self.assertEqual(item["source"], "fundamental.stocks.board")
        self.assertEqual(item["quality_status"], "unverified")
        self.assertIsNone(item["dataset_version"])
        self.assertIsNone(item["fetched_at"])
        self.assertIsNone(item["effective_from"])
        self.assertFalse(item["pit_capable"])
        self.assertFalse(item["historical_research_usable"])
        self.assertFalse(item["backtest_usable"])
        self.assertFalse(payload["observed_only"])
        self.assertEqual(payload["research_readiness"], "not_granted")
        self.assertFalse(payload["tradable"])
        self.assertFalse(payload["order_created"])
        self.assertEqual(db.params[0]["board"], "主板")
        self.assertIn("fundamental.stocks", db.sql[0])
        self.assertIn("ORDER BY MAX(stock.updated_at) DESC NULLS LAST, stock.board", db.sql[1])
        self.assertFalse(any(f"{operation} " in statement.upper() for statement in db.sql for operation in ("INSERT", "UPDATE", "DELETE")))

    def test_exchange_board_snapshot_route_requires_market_read_scope(self):
        route = next(item for item in market.router.routes if item.path == "/exchange-boards")
        self.assertEqual(route.methods, {"GET"})
        self.assertEqual(route_access("GET", "/api/v1/market/exchange-boards").scope, "market:read")

    def test_market_sentiment_is_unavailable_without_observed_evidence_or_a_generated_score(self):
        with patch("app.api.market.get_db", side_effect=AssertionError("sentiment endpoint must not fabricate a fallback score")):
            response = asyncio.run(market.get_market_sentiment(page=2, page_size=1))

        payload = response.data
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["availability_status"], "unavailable")
        self.assertEqual(payload["data_semantics"], "unavailable")
        self.assertFalse(payload["observed_only"])
        self.assertFalse(payload["derived"])
        self.assertFalse(payload["derived_from_observed"])
        self.assertIsNone(payload["score"])
        self.assertEqual(payload["evidence_refs"], [])
        self.assertIsNone(payload["provider"])
        self.assertIsNone(payload["source_published_at"])
        self.assertIsNone(payload["algorithm_version"])
        self.assertEqual(payload["formal_model"], "market.sentiment_derivations")
        self.assertEqual(payload["lineage_contract"]["allowed_semantics"], ["derived", "derived_from_observed"])
        self.assertTrue(payload["lineage_contract"]["observed_forbidden"])
        self.assertFalse(payload["historical_research_usable"])
        self.assertFalse(payload["backtest_usable"])
        self.assertEqual(payload["research_readiness"], "not_granted")
        self.assertFalse(payload["tradable"])
        self.assertFalse(payload["order_created"])

    def test_market_sentiment_route_requires_market_read_scope(self):
        route = next(item for item in market.router.routes if item.path == "/sentiment")
        self.assertEqual(route.methods, {"GET"})
        self.assertEqual(route_access("GET", "/api/v1/market/sentiment").scope, "market:read")

    def test_future_models_preserve_independent_semantics_without_legacy_backfill(self):
        migration = (Path(__file__).resolve().parents[1] / "alembic" / "versions" / "041_p2_2_market_observation_semantics.py").read_text(encoding="utf-8")
        for table in ("industry_classification_observations", "concept_board_memberships", "exchange_board_observations", "sentiment_derivations"):
            self.assertIn(f"market.{table}", migration)
        self.assertIn("semantic_kind IN ('derived', 'derived_from_observed')", migration)
        self.assertNotIn("fundamental.stocks.sector", migration)


if __name__ == "__main__":
    unittest.main()
