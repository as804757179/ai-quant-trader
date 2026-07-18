import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("SECRET_KEY", "contract-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.api import data  # noqa: E402
from app.api import rules  # noqa: E402
from app.core.auth import route_access  # noqa: E402
from app.data.certification import DataCertificationService  # noqa: E402
from app.data.quality_validator import KlineQualityValidator  # noqa: E402


class _Result:
    def __init__(self, *, one=None, rows=None):
        self._one = one
        self._rows = rows or []

    def mappings(self):
        return self

    def one(self):
        return self._one

    def all(self):
        return self._rows


class _Db:
    def __init__(self, results=None):
        self._results = list(results or [])
        self.sql = []
        self.params = []

    async def execute(self, statement, params):
        self.sql.append(str(statement))
        self.params.append(params)
        return self._results.pop(0) if self._results else _Result()


class _DbContext:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class QualityResultAuditTests(unittest.TestCase):
    def test_validator_exposes_actual_rule_results_without_changing_rejection(self):
        result = KlineQualityValidator().validate_rows(
            [], provider="unknown", source="synthetic", is_synthetic=True
        )

        rules = {item.rule_code: item for item in result.rule_results}
        self.assertFalse(result.passed)
        self.assertEqual(result.score, 40.0)
        self.assertEqual(rules["rows_present"].result, "fail")
        self.assertEqual(rules["provider_identified"].result, "fail")
        self.assertEqual(rules["source_identified"].result, "pass")
        self.assertEqual(rules["synthetic_source_rejected"].result, "fail")
        self.assertEqual(rules["required_fields"].result, "not_evaluated")

    def test_create_batch_writes_append_only_rule_results_with_real_input_hash(self):
        db = _Db()
        service = DataCertificationService()
        batch_id, result = asyncio.run(
            service.create_batch(
                db,
                [],
                provider="provider-a",
                source="source-a",
                period="1d",
            )
        )

        self.assertFalse(result.passed)
        self.assertEqual(len(db.sql), 2)
        self.assertIn("INSERT INTO market.data_batches", db.sql[0])
        self.assertIn("INSERT INTO market.data_quality_results", db.sql[1])
        audit_rows = db.params[1]
        self.assertEqual(len(audit_rows), len(result.rule_results))
        self.assertTrue(all(row["batch_id"] == batch_id for row in audit_rows))
        self.assertTrue(all(len(row["input_hash"]) == 64 for row in audit_rows))
        self.assertTrue(any(row["rule_code"] == "rows_present" and row["result"] == "fail" for row in audit_rows))

    def test_route_reads_server_pagination_and_never_changes_certification(self):
        route = next(item for item in data.router.routes if item.path == "/quality-results")
        self.assertEqual(route.methods, {"GET"})
        self.assertEqual(route_access("GET", "/api/v1/data/quality-results").scope, "market:read")
        db = _Db(
            [
                _Result(
                    one={
                        "total": 2,
                        "passed": 1,
                        "failed": 1,
                        "not_evaluated": 0,
                        "latest_evaluated_at": None,
                    }
                ),
                _Result(
                    rows=[
                        {
                            "quality_result_id": "result-1",
                            "batch_id": "batch-1",
                            "rule_code": "ohlc_validity",
                            "rule_version": "kline-quality-v1",
                            "audit_scope": "batch",
                            "result": "fail",
                            "reject_reason": "invalid OHLC",
                            "input_hash": "a" * 64,
                            "created_at": None,
                            "stock_code": "000001.SZ",
                            "provider": "provider-a",
                            "source": "source-a",
                            "period": "1d",
                            "fetch_time": None,
                            "importer_version": "v1",
                        }
                    ]
                ),
            ]
        )
        with patch("app.api.data.get_db", return_value=_DbContext(db)):
            response = asyncio.run(
                data.list_quality_results(
                    batch_id=None,
                    stock_code=None,
                    rule_code=None,
                    result=None,
                    page=1,
                    page_size=1,
                )
            )

        self.assertEqual(response.data["summary"]["failed"], 1)
        self.assertTrue(response.data["has_more"])
        self.assertEqual(response.data["items"][0]["rule_code"], "ohlc_validity")
        self.assertEqual(response.data["research_readiness"], "not_granted")
        self.assertFalse(response.data["tradable"])
        self.assertIn("ORDER BY quality.created_at DESC, quality.quality_result_id DESC", db.sql[1])
        self.assertIn("LIMIT :limit OFFSET :offset", db.sql[1])
        self.assertFalse(
            any(
                operation in statement.upper()
                for statement in db.sql
                for operation in ("UPDATE", "DELETE")
            )
        )

    def test_blocker_route_preserves_unknown_readiness_linkage(self):
        route = next(item for item in data.router.routes if item.path == "/blockers")
        self.assertEqual(route.methods, {"GET"})
        self.assertEqual(route_access("GET", "/api/v1/data/blockers").scope, "market:read")
        db = _Db(
            [
                _Result(one={"total": 1, "unresolved": 1, "provider_missing": 0, "latest_reviewed_at": None}),
                _Result(rows=[{"blocker_id": "review-1", "stock_code": "000001.SZ", "trading_date": None, "classification": "unresolved", "status": "unresolved", "readiness_blocking": None, "readiness_linkage_status": "not_recorded"}]),
            ]
        )
        with patch("app.api.data.get_db", return_value=_DbContext(db)):
            response = asyncio.run(
                data.list_data_blockers(stock_code=None, date_from=None, date_to=None, classification=None, status=None, page=1, page_size=50)
            )

        self.assertEqual(response.data["items"][0]["readiness_linkage_status"], "not_recorded")
        self.assertIsNone(response.data["items"][0]["readiness_blocking"])
        self.assertFalse(response.data["tradable"])
        self.assertIn("ORDER BY blocker.trading_date DESC NULLS LAST, blocker.blocker_id DESC", db.sql[1])

    def test_provider_validation_route_reads_audit_rows_without_fallback(self):
        route = next(item for item in data.router.routes if item.path == "/provider-validations")
        self.assertEqual(route.methods, {"GET"})
        db = _Db([_Result(one={"total": 1, "passed": 0, "review": 0, "failed": 1, "latest_reviewed_at": None}), _Result(rows=[{"stock_code": "000001.SZ", "field": "close", "conclusion": "FAIL"}])])
        with patch("app.api.data.get_db", return_value=_DbContext(db)):
            response = asyncio.run(data.list_provider_validations(stock_code=None, date_from=None, date_to=None, field=None, conclusion=None, page=1, page_size=50))
        self.assertEqual(response.data["items"][0]["conclusion"], "FAIL")
        self.assertFalse(response.data["tradable"])
        self.assertIn("jsonb_each", db.sql[0])
        self.assertIn("ORDER BY validation.trading_date DESC", db.sql[1])

    def test_calendar_route_is_read_only_and_does_not_use_weekday_fallback(self):
        route = next(item for item in rules.router.routes if item.path == "/trading-calendar")
        self.assertEqual(route.methods, {"GET"})
        db = _Db([_Result(one={"total": 1, "confirmed": 1, "unresolved": 0, "coverage_from": None, "coverage_to": None}), _Result(rows=[])])
        with patch("app.api.rules.get_db", return_value=_DbContext(db)):
            response = asyncio.run(rules.list_trading_calendar(exchange=None, date_from=None, date_to=None, status=None, page=1, page_size=50))
        self.assertEqual(route_access("GET", "/api/v1/rules/trading-calendar").scope, "market:read")
        self.assertEqual(response.data["source"], "market.trading_calendar")
        self.assertIn("ORDER BY calendar.trading_date DESC, calendar.exchange", db.sql[1])

    def test_trading_rules_route_returns_versioned_records_without_trading_authority(self):
        route = next(item for item in rules.router.routes if item.path == "/trading")
        self.assertEqual(route.methods, {"GET"})
        response = asyncio.run(rules.list_trading_rules(
            exchange="SH", board=None, security_status=None,
            date_from=None, date_to=None, rule_version=None, page=1, page_size=2,
        ))
        self.assertEqual(route_access("GET", "/api/v1/rules/trading").scope, "market:read")
        self.assertEqual(response.data["registry_version"], "ashare-market-rules-v1")
        self.assertFalse(response.data["tradable"])
        self.assertFalse(response.data["order_created"])
        self.assertTrue(response.data["has_more"])
        self.assertTrue(all(item["source_hash"] is None for item in response.data["items"]))
        self.assertTrue(all(item["rule_type"] != "slippage_rate" for item in response.data["items"]))


if __name__ == "__main__":
    unittest.main()
