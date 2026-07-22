from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import TestCase

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "free-observation-cycle-test-secret-key-32chars")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://free-observation@localhost/unused")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/unused")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data.free_observation_dual_ma import FreeObservationDualMaEvaluator  # noqa: E402
from app.data.tushare_free_observation import TUSHARE_DATASET_VERSION, TUSHARE_PROVIDER, TUSHARE_SOURCE  # noqa: E402
from app.strategy.version_service import StrategyVersionService  # noqa: E402


class FreeObservationCycleCommandTests(TestCase):
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

    def test_command_creates_the_three_linked_observation_files(self) -> None:
        script = BACKEND_ROOT / "scripts" / "run_free_observation_cycle.py"
        artifacts = [self._artifact("2026-07-17", 10.0), self._artifact("2026-07-20", 10.0), self._artifact("2026-07-21", 10.0), self._artifact("2026-07-22", 9.0), self._artifact("2026-07-23", 8.0), self._artifact("2026-07-24", 12.0)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_args = []
            for index, artifact in enumerate(artifacts):
                path = root / f"artifact-{index}.json"
                path.write_text(json.dumps(artifact), encoding="utf-8")
                artifact_args.extend(["--artifact", str(path)])
            snapshot_path = root / "strategy.json"
            snapshot_path.write_text(json.dumps(self.snapshot), encoding="utf-8")
            candidate_path, ledger_path, report_path = root / "candidate.json", root / "ledger.json", root / "report.json"
            command = [sys.executable, str(script), *artifact_args, "--strategy-snapshot", str(snapshot_path), "--initial-cash", "100000", "--candidate-output", str(candidate_path), "--ledger-output", str(ledger_path), "--report-output", str(report_path), "--confirm-free-observation"]
            result = subprocess.run(command, cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(ledger["candidate_result_hash"], candidate["result_hash"])
            self.assertEqual(report["candidate_result_hash"], candidate["result_hash"])
            self.assertEqual(report["ledger_hash"], ledger["ledger_hash"])
            self.assertFalse(report["formal_use"])
            self.assertFalse(report["tradable"])
            repeated = subprocess.run(command, cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(repeated.returncode, 2)

    def test_command_refuses_production_and_partial_output_setup(self) -> None:
        script = BACKEND_ROOT / "scripts" / "run_free_observation_cycle.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact.json"
            snapshot = root / "strategy.json"
            artifact.write_text(json.dumps(self._artifact("2026-07-22", 10.0)), encoding="utf-8")
            snapshot.write_text(json.dumps(self.snapshot), encoding="utf-8")
            candidate_path, ledger_path, report_path = root / "candidate.json", root / "ledger.json", root / "report.json"
            candidate_path.write_text("already exists", encoding="utf-8")
            command = [sys.executable, str(script), "--artifact", str(artifact), "--strategy-snapshot", str(snapshot), "--initial-cash", "100", "--candidate-output", str(candidate_path), "--ledger-output", str(ledger_path), "--report-output", str(report_path), "--confirm-free-observation"]
            result = subprocess.run(command, cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(ledger_path.exists())
            self.assertFalse(report_path.exists())
            environment = dict(os.environ)
            environment["APP_ENV"] = "production"
            production = subprocess.run(command, cwd=BACKEND_ROOT, env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(production.returncode, 2)
