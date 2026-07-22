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
os.environ.setdefault("SECRET_KEY", "free-observation-ledger-test-secret-key-32chars")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://free-observation@localhost/unused")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/unused")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data.free_observation_dual_ma import FreeObservationDualMaEvaluator  # noqa: E402
from app.data.free_observation_ledger import FreeObservationLedger, FreeObservationLedgerError  # noqa: E402
from app.data.tushare_free_observation import TUSHARE_DATASET_VERSION, TUSHARE_PROVIDER, TUSHARE_SOURCE  # noqa: E402
from app.shadow.contracts import RELEASE_LOCK_KEYS  # noqa: E402
from app.strategy.version_service import StrategyVersionService  # noqa: E402


class FreeObservationLedgerTests(TestCase):
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
            "fetched_at": datetime(2026, 7, 22, 15, 5, tzinfo=timezone.utc).isoformat(),
        }
        artifact["batch_hash"] = FreeObservationDualMaEvaluator._hash({key: artifact[key] for key in ("provider", "source", "dataset_version", "trade_date", "raw_payload_hash", "rows")})
        return artifact

    def _candidate(self, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        return FreeObservationDualMaEvaluator.evaluate(artifacts=artifacts, strategy_snapshot=self.snapshot).as_dict()

    def test_deterministic_open_close_and_event_reconciliation(self) -> None:
        opening = [self._artifact("2026-07-17", 10.0), self._artifact("2026-07-20", 10.0), self._artifact("2026-07-21", 10.0), self._artifact("2026-07-22", 9.0), self._artifact("2026-07-23", 8.0), self._artifact("2026-07-24", 12.0)]
        candidate = self._candidate(opening)
        reports = [FreeObservationLedger.apply(candidate_document=candidate, artifacts=opening, initial_cash=Decimal("100000")) for _ in range(3)]
        self.assertEqual({report["ledger_hash"] for report in reports}, {reports[0]["ledger_hash"]})
        opened = reports[0]
        self.assertEqual(opened["account_snapshot"]["positions"]["000001.SZ"]["quantity"], 1600)
        closing = [*opening, self._artifact("2026-07-25", 8.0), self._artifact("2026-07-26", 7.0)]
        closed = FreeObservationLedger.apply(candidate_document=self._candidate(closing), artifacts=closing, prior_ledger=opened)
        self.assertEqual(closed["account_snapshot"]["positions"], {})
        self.assertTrue(closed["reconciliation"]["matched"])
        self.assertFalse(closed["tradable"])
        self.assertFalse(closed["order_created"])

    def test_rejects_invalid_inputs_and_prior_hash(self) -> None:
        artifact = self._artifact("2026-07-22", 10.0)
        candidate = self._candidate([artifact])
        artifact["data_mode"] = "replay"
        with self.assertRaises(FreeObservationLedgerError) as invalid:
            FreeObservationLedger.apply(candidate_document=candidate, artifacts=[artifact], initial_cash=Decimal("100"))
        self.assertEqual(invalid.exception.code, "FREE_OBSERVATION_INPUT_INVALID")
        artifact = self._artifact("2026-07-22", 10.0)
        report = FreeObservationLedger.apply(candidate_document=self._candidate([artifact]), artifacts=[artifact], initial_cash=Decimal("100"))
        report["ledger_hash"] = "0" * 64
        with self.assertRaises(FreeObservationLedgerError) as tampered:
            FreeObservationLedger.apply(candidate_document=self._candidate([artifact]), artifacts=[artifact], prior_ledger=report)
        self.assertEqual(tampered.exception.code, "FREE_OBSERVATION_LEDGER_HASH_MISMATCH")

    def test_rejects_time_regression_and_open_release_lock(self) -> None:
        first_artifact = self._artifact("2026-07-22", 10.0)
        first = FreeObservationLedger.apply(
            candidate_document=self._candidate([first_artifact]), artifacts=[first_artifact], initial_cash=Decimal("100")
        )
        older_artifact = self._artifact("2026-07-21", 10.0)
        with self.assertRaises(FreeObservationLedgerError) as regressed:
            FreeObservationLedger.apply(
                candidate_document=self._candidate([older_artifact]), artifacts=[older_artifact], prior_ledger=first
            )
        self.assertEqual(regressed.exception.code, "FREE_OBSERVATION_LEDGER_TIME_REGRESSION")
        with patch("app.data.free_observation_ledger.settings.TRADING_EXECUTION_ENABLED", True):
            with self.assertRaises(FreeObservationLedgerError) as locked:
                FreeObservationLedger.apply(
                    candidate_document=self._candidate([first_artifact]), artifacts=[first_artifact], initial_cash=Decimal("100")
                )
        self.assertEqual(locked.exception.code, "FREE_OBSERVATION_RELEASE_LOCK_INVALID")

    def test_ledger_has_no_formal_writes_or_lock_change(self) -> None:
        artifact = self._artifact("2026-07-22", 10.0)
        report = FreeObservationLedger.apply(candidate_document=self._candidate([artifact]), artifacts=[artifact], initial_cash=Decimal("100"))
        self.assertEqual(report["formal_write_counts"], {"order": 0, "execution": 0, "capital": 0, "position": 0, "external_provider": 0})
        self.assertTrue(all(report["release_locks"][key] is False for key in RELEASE_LOCK_KEYS))
        self.assertFalse(report["formal_use"])
        self.assertEqual(report["blocked_from"], ["certified_store", "formal_p3", "formal_p4", "p5", "trade_execution"])
        source = (BACKEND_ROOT / "app" / "data" / "free_observation_ledger.py").read_text(encoding="utf-8")
        for forbidden in ("sqlalchemy", "asyncpg", "httpx", "requests", "SimulationTrader", "LiveTrader"):
            self.assertNotIn(forbidden, source)

    def test_command_writes_new_file_and_refuses_production(self) -> None:
        artifact = self._artifact("2026-07-22", 10.0)
        candidate = self._candidate([artifact])
        script = BACKEND_ROOT / "scripts" / "apply_free_observation_ledger.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_path, artifact_path, output_path = root / "candidate.json", root / "artifact.json", root / "ledger.json"
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
            command = [sys.executable, str(script), "--candidate", str(candidate_path), "--artifact", str(artifact_path), "--initial-cash", "1000", "--output", str(output_path), "--confirm-free-observation"]
            result = subprocess.run(command, cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(output_path.read_text(encoding="utf-8"))["formal_use"])
            repeated = subprocess.run(command, cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(repeated.returncode, 2)
            environment = dict(os.environ)
            environment["APP_ENV"] = "production"
            production = subprocess.run(command, cwd=BACKEND_ROOT, env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(production.returncode, 2)
