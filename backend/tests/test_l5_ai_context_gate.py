import asyncio
from datetime import datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.ai.orchestrator import AgentOrchestrator
from app.data.service import AI_CONTEXT_POLICY_VERSION, DataService
from app.screener.engine import ScreenerEngine
from app.services.ai_service import AIService


class _ContextDataService(DataService):
    def __init__(self, *, news=None):
        self._news = [{"title": "news"}] if news is None else news

    async def get_quote(self, _code):
        return {"price": 10.0, "prev_close": 9.5, "amount": 1000}

    async def get_certified_kline(self, _code, period, *_args):
        return [
            {
                "time": "2026-07-16T15:00:00",
                "open": 9.0,
                "high": 10.2,
                "low": 8.8,
                "close": 10.0,
                "volume": 100,
            }
        ] if period in {"1d", "60min"} else []

    async def get_fund_flow(self, _code, _days):
        return [{"main_net_in": 100.0, "north_net_in": 50.0}]

    async def get_news(self, _code, _limit):
        if isinstance(self._news, Exception):
            raise self._news
        return self._news

    async def get_latest_financial_report(self, _code):
        return {"report_date": "2026-03-31", "revenue": 100.0}

    async def get_north_flow(self, _code):
        return {"today": 50.0, "five_day": 50.0}

    async def get_dragon_tiger(self, _code):
        return []

    async def _get_stock_info(self, _code):
        return {}


class _NeverRunAgent:
    async def run_safe(self, _context):
        raise AssertionError("context gate must prevent model invocation")


class _NeverRunRisk:
    model = "never-run"

    def evaluate(self, _context, _results):
        raise AssertionError("context gate must prevent risk evaluation")


class _NeverRunRag:
    async def build_rag_context(self, _code):
        raise AssertionError("context gate must prevent RAG invocation")


class _Rows:
    def __init__(self, record):
        self.record = record

    def mappings(self):
        return self

    def first(self):
        return self.record


class _Db:
    def __init__(self, record):
        self.record = record

    async def execute(self, *_args, **_kwargs):
        return _Rows(self.record)


class _DbContext:
    def __init__(self, record):
        self.db = _Db(record)

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return False


class AiContextGateTests(unittest.TestCase):
    def test_full_context_marks_legacy_sources_as_blockers(self):
        context = asyncio.run(_ContextDataService().get_full_context("600000"))

        self.assertEqual(context["analysis_context_policy_version"], AI_CONTEXT_POLICY_VERSION)
        self.assertEqual(context["analysis_context_status"], "blocked")
        self.assertEqual(context["analysis_context_sources"]["kline_1d"], "ready")
        self.assertEqual(
            context["analysis_context_sources"]["financial_report"],
            "not_research_authorized",
        )
        self.assertEqual(context["analysis_context_sources"]["news"], "not_research_authorized")
        self.assertEqual(context["analysis_context_sources"]["rag"], "not_research_authorized")
        self.assertEqual(
            context["analysis_context_sources"]["quote"], "provenance_unverified"
        )

    def test_full_context_preserves_source_failure_as_blocker(self):
        context = asyncio.run(
            _ContextDataService(news=TimeoutError("upstream timeout")).get_full_context(
                "600000"
            )
        )

        self.assertEqual(context["news"], [])
        self.assertEqual(context["analysis_context_sources"]["news"], "unavailable")
        self.assertIn(
            {"source": "news", "status": "unavailable", "reason": "关键数据源请求失败。"},
            context["analysis_context_blockers"],
        )

    def test_orchestrator_blocks_missing_or_rejected_context_before_models(self):
        never = _NeverRunAgent()
        orchestrator = AgentOrchestrator(
            trend_agent=never,
            fundamental_agent=never,
            sentiment_agent=never,
            shortterm_agent=never,
            risk_agent=_NeverRunRisk(),
            rag_engine=_NeverRunRag(),
        )

        result = asyncio.run(
            orchestrator.run(
                "600000",
                {
                    "analysis_context_status": "blocked",
                    "analysis_context_blockers": [
                        {"source": "news", "status": "unavailable"}
                    ],
                },
            )
        )

        self.assertEqual(result["signal"]["action"], "HOLD")
        self.assertEqual(result["signal"]["confidence"], 0.0)
        self.assertEqual(set(result["agent_statuses"]), {
            "trend", "fundamental", "sentiment", "shortterm", "risk"
        })

    def test_cache_rejects_ready_signal_after_context_revocation(self):
        record = {
            "id": "00000000-0000-0000-0000-000000000001",
            "action": "BUY",
            "confidence": 0.9,
            "risk_level": "LOW",
            "price_at": 10.0,
            "reason": "legacy buy",
            "agent_votes": {},
            "raw_agent_output": {
                "analysis_context_policy_version": AI_CONTEXT_POLICY_VERSION,
                "analysis_context_status": "ready",
                "historical_data_status": "certified",
            },
            "signal_time": datetime(2026, 7, 16),
            "valid_until": None,
        }
        service = AIService.__new__(AIService)
        revoked_context = {
            "analysis_context_policy_version": AI_CONTEXT_POLICY_VERSION,
            "analysis_context_status": "blocked",
        }

        with patch("app.services.ai_service.get_db", return_value=_DbContext(record)):
            cached = asyncio.run(service.get_valid_signal("600000", context=revoked_context))

        self.assertIsNone(cached)

    def test_current_signal_reloads_context_before_cache_lookup(self):
        record = {
            "id": "00000000-0000-0000-0000-000000000001",
            "action": "BUY",
            "confidence": 0.9,
            "risk_level": "LOW",
            "price_at": 10.0,
            "reason": "legacy buy",
            "agent_votes": {},
            "raw_agent_output": {
                "analysis_context_policy_version": AI_CONTEXT_POLICY_VERSION,
                "analysis_context_status": "ready",
                "historical_data_status": "certified",
            },
            "signal_time": datetime(2026, 7, 16),
            "valid_until": None,
        }
        service = AIService.__new__(AIService)
        service.data_service = _ContextDataService()

        with patch("app.services.ai_service.get_db", return_value=_DbContext(record)):
            cached = asyncio.run(service.get_current_valid_signal("600000"))

        self.assertIsNone(cached)

    def test_response_never_marks_ai_signal_as_tradable(self):
        service = AIService.__new__(AIService)
        response = service._build_response(
            code="600000",
            signal_id="00000000-0000-0000-0000-000000000001",
            data_quality_score=100.0,
            historical_data_status="certified",
            analysis_context_status="ready",
            result={
                "signal": {
                    "action": "BUY",
                    "confidence": 0.9,
                    "risk_level": "LOW",
                    "reason": "test",
                }
            },
        )

        self.assertFalse(response.tradable)

    def test_theme_screening_refuses_legacy_announcement_matching(self):
        result = asyncio.run(
            ScreenerEngine(release_enabled=True).screen_by_theme("AI芯片", limit=10)
        )

        self.assertEqual(result["items"], [])
        self.assertEqual(result["release_status"], "blocked")
        self.assertEqual(
            result["blocked_reason"], "THEME_EVIDENCE_READINESS_NOT_IMPLEMENTED"
        )


if __name__ == "__main__":
    unittest.main()
