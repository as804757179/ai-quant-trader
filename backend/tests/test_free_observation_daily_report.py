from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "free-observation-daily-report-test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://free-observation@localhost/unused")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/unused")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data.free_observation_daily_report import FreeObservationDailyReport, FreeObservationDailyReportError  # noqa: E402
from app.data.free_observation_dual_ma import FreeObservationDualMaEvaluator  # noqa: E402
from app.data.free_observation_ledger import FreeObservationLedger  # noqa: E402
from app.data.free_observation_review import FreeObservationReview  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.data.tushare_free_observation import TUSHARE_DATASET_VERSION, TUSHARE_PROVIDER, TUSHARE_SOURCE  # noqa: E402
from app.shadow.contracts import RELEASE_LOCK_KEYS  # noqa: E402
from app.strategy.version_service import StrategyVersionService  # noqa: E402


class FreeObservationDailyReportTests(TestCase):
    def setUp(self) -> None:
        params = {"fast_period": 2, "slow_period": 5, "position_pct": 0.2}
        catalog_hash = StrategyVersionService.catalog_hash("dual_ma")
        self.snapshot = {
            "strategy_type": "dual_ma", "strategy_id": 1, "version_id": 5, "version": 5,
            "enabled": True, "params": params, "catalog_hash": catalog_hash,
            "config_hash": StrategyVersionService.config_hash(strategy_type="dual_ma", enabled=True, params=params, catalog_hash=catalog_hash),
        }

    def _artifact(self, trade_date: str, close: float) -> dict[str, Any]:
        row = {"ts_code": "000001.SZ", "trade_date": trade_date.replace("-", ""), "open": close, "high": close, "low": close, "close": close}
        row["row_hash"] = FreeObservationDualMaEvaluator._hash(row)
        artifact = {
            "provider": TUSHARE_PROVIDER, "source": TUSHARE_SOURCE, "dataset_version": TUSHARE_DATASET_VERSION,
            "trade_date": trade_date, "raw_payload_hash": "a" * 64, "rows": [row],
            "data_mode": "free_observation", "data_qualification": "unverified", "formal_use": False,
            "available_at": None, "available_at_status": "unverified",
            "fetched_at": datetime.fromisoformat(f"{trade_date}T15:05:00+00:00").isoformat(),
        }
        artifact["batch_hash"] = FreeObservationDualMaEvaluator._hash({key: artifact[key] for key in ("provider", "source", "dataset_version", "trade_date", "raw_payload_hash", "rows")})
        return artifact

    def _documents(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        artifacts = [self._artifact("2026-07-17", 10.0), self._artifact("2026-07-20", 10.0), self._artifact("2026-07-21", 10.0), self._artifact("2026-07-22", 9.0), self._artifact("2026-07-23", 8.0), self._artifact("2026-07-24", 12.0)]
        candidate = FreeObservationDualMaEvaluator.evaluate(artifacts=artifacts, strategy_snapshot=self.snapshot).as_dict()
        ledger = FreeObservationLedger.apply(candidate_document=candidate, artifacts=artifacts, initial_cash=Decimal("100000"))
        review = FreeObservationReview.evaluate(candidate_document=candidate, artifacts=[*artifacts, self._artifact("2026-07-25", 13.0)])
        return candidate, ledger, review

    def test_builds_deterministic_read_only_report(self) -> None:
        candidate, ledger, review = self._documents()
        first = FreeObservationDailyReport.build(candidate_document=candidate, ledger_document=ledger, review_document=review)
        second = FreeObservationDailyReport.build(candidate_document=candidate, ledger_document=ledger, review_document=review)
        self.assertEqual(first["report_hash"], second["report_hash"])
        self.assertEqual(first["candidate_summary"], {"BUY_OBSERVATION": 1})
        self.assertEqual(first["direction_review_summary"], {"DIRECTION_MATCHED": 1})
        self.assertEqual(first["formal_write_counts"], {"order": 0, "execution": 0, "capital": 0, "position": 0, "external_provider": 0})
        self.assertTrue(all(first["release_locks"][key] is False for key in RELEASE_LOCK_KEYS))
        self.assertFalse(first["formal_use"])
        self.assertFalse(first["tradable"])

    def test_rejects_lineage_and_review_hash_mismatch(self) -> None:
        candidate, ledger, review = self._documents()
        ledger["candidate_result_hash"] = "0" * 64
        ledger_payload = {
            key: ledger.get(key)
            for key in (
                "data_mode", "data_qualification", "formal_use", "ruleset_version", "candidate_result_hash",
                "input_batch_hashes", "events", "account_snapshot", "formal_write_counts", "release_locks",
            )
        }
        ledger["ledger_hash"] = FreeObservationLedger._hash(ledger_payload)
        with self.assertRaises(FreeObservationDailyReportError) as lineage:
            FreeObservationDailyReport.build(candidate_document=candidate, ledger_document=ledger)
        self.assertEqual(lineage.exception.code, "FREE_OBSERVATION_REPORT_LINEAGE_MISMATCH")
        candidate, ledger, review = self._documents()
        review["review_hash"] = "0" * 64
        with self.assertRaises(FreeObservationDailyReportError) as invalid_review:
            FreeObservationDailyReport.build(candidate_document=candidate, ledger_document=ledger, review_document=review)
        self.assertEqual(invalid_review.exception.code, "FREE_OBSERVATION_REPORT_REVIEW_HASH_MISMATCH")

    def test_rejects_current_open_release_lock(self) -> None:
        candidate, ledger, review = self._documents()
        with patch.object(settings, "AI_ORDER_ENABLED", True):
            with self.assertRaises(FreeObservationDailyReportError) as locked:
                FreeObservationDailyReport.build(candidate_document=candidate, ledger_document=ledger, review_document=review)
        self.assertEqual(locked.exception.code, "FREE_OBSERVATION_REPORT_LOCK_INVALID")

    def test_command_writes_new_file_and_refuses_production(self) -> None:
        candidate, ledger, review = self._documents()
        script = BACKEND_ROOT / "scripts" / "report_free_observation_day.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_path, ledger_path, review_path, output_path = root / "candidate.json", root / "ledger.json", root / "review.json", root / "report.json"
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            review_path.write_text(json.dumps(review), encoding="utf-8")
            command = [sys.executable, str(script), "--candidate", str(candidate_path), "--ledger", str(ledger_path), "--review", str(review_path), "--output", str(output_path), "--confirm-free-observation"]
            result = subprocess.run(command, cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(output_path.read_text(encoding="utf-8"))["formal_use"])
            repeated = subprocess.run(command, cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(repeated.returncode, 2)
            environment = dict(os.environ)
            environment["APP_ENV"] = "production"
            production = subprocess.run(command, cwd=BACKEND_ROOT, env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(production.returncode, 2)
