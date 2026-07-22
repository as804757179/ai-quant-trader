from __future__ import annotations

import os
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import TestCase

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "free-observation-test-secret-key-32chars")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://free-observation@localhost/unused")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/unused")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data.free_observation_dual_ma import (
    FreeObservationDualMaEvaluator,
    FreeObservationEvaluationError,
)
from app.data.tushare_free_observation import TUSHARE_DATASET_VERSION, TUSHARE_PROVIDER, TUSHARE_SOURCE
from app.strategy.version_service import StrategyVersionService


class FreeObservationDualMaTests(TestCase):
    def setUp(self) -> None:
        self.params = {"fast_period": 2, "slow_period": 5, "position_pct": 0.2}
        catalog_hash = StrategyVersionService.catalog_hash("dual_ma")
        self.snapshot = {
            "strategy_type": "dual_ma",
            "strategy_id": 1,
            "version_id": 5,
            "version": 5,
            "enabled": True,
            "params": self.params,
            "catalog_hash": catalog_hash,
            "config_hash": StrategyVersionService.config_hash(
                strategy_type="dual_ma", enabled=True, params=self.params, catalog_hash=catalog_hash
            ),
        }

    def _artifact(self, trade_date: str, close: float) -> dict[str, Any]:
        row = {"ts_code": "000001.SZ", "trade_date": trade_date.replace("-", ""), "open": close, "high": close, "low": close, "close": close}
        row["row_hash"] = FreeObservationDualMaEvaluator._hash(row)
        artifact = {
            "provider": TUSHARE_PROVIDER,
            "source": TUSHARE_SOURCE,
            "dataset_version": TUSHARE_DATASET_VERSION,
            "trade_date": trade_date,
            "raw_payload_hash": "a" * 64,
            "rows": [row],
            "data_mode": "free_observation",
            "data_qualification": "unverified",
            "formal_use": False,
            "available_at": None,
            "available_at_status": "unverified",
            "fetched_at": datetime(2026, 7, 22, 15, 5, tzinfo=timezone.utc).isoformat(),
        }
        artifact["batch_hash"] = FreeObservationDualMaEvaluator._hash(
            {key: artifact[key] for key in ("provider", "source", "dataset_version", "trade_date", "raw_payload_hash", "rows")}
        )
        return artifact

    def test_generates_deterministic_observation_only_candidate(self) -> None:
        artifacts = [
            self._artifact("2026-07-17", 10.0),
            self._artifact("2026-07-20", 10.0),
            self._artifact("2026-07-21", 10.0),
            self._artifact("2026-07-22", 9.0),
            self._artifact("2026-07-23", 8.0),
            self._artifact("2026-07-24", 12.0),
        ]
        first = FreeObservationDualMaEvaluator.evaluate(artifacts=artifacts, strategy_snapshot=self.snapshot)
        second = FreeObservationDualMaEvaluator.evaluate(artifacts=artifacts, strategy_snapshot=self.snapshot)
        candidate = first.candidates[0]
        self.assertEqual(first.result_hash, second.result_hash)
        self.assertEqual(candidate.would_action, "BUY_OBSERVATION")
        self.assertTrue(candidate.observation_only)
        self.assertFalse(candidate.tradable)
        self.assertFalse(candidate.order_created)
        self.assertFalse(first.as_dict()["formal_use"])
        self.assertEqual(first.as_dict()["research_readiness"], "not_granted")

    def test_rejects_hash_mismatch_and_formal_input(self) -> None:
        artifact = self._artifact("2026-07-22", 10.0)
        artifact["batch_hash"] = "0" * 64
        with self.assertRaisesRegex(FreeObservationEvaluationError, "批次 Hash"):
            FreeObservationDualMaEvaluator.evaluate(artifacts=[artifact], strategy_snapshot=self.snapshot)
        artifact = self._artifact("2026-07-22", 10.0)
        artifact["formal_use"] = True
        with self.assertRaisesRegex(FreeObservationEvaluationError, "伪装为正式"):
            FreeObservationDualMaEvaluator.evaluate(artifacts=[artifact], strategy_snapshot=self.snapshot)

    def test_rejects_invalid_strategy_snapshot_and_duplicate_rows(self) -> None:
        bad_snapshot = {**self.snapshot, "config_hash": "0" * 64}
        with self.assertRaisesRegex(FreeObservationEvaluationError, "Hash 不一致"):
            FreeObservationDualMaEvaluator.evaluate(
                artifacts=[self._artifact("2026-07-22", 10.0)], strategy_snapshot=bad_snapshot
            )
        duplicate = self._artifact("2026-07-22", 10.0)
        with self.assertRaisesRegex(FreeObservationEvaluationError, "重复股票交易日"):
            FreeObservationDualMaEvaluator.evaluate(
                artifacts=[duplicate, duplicate], strategy_snapshot=self.snapshot
            )

    def test_command_writes_new_observation_only_candidate_file(self) -> None:
        script = BACKEND_ROOT / "scripts" / "evaluate_free_observation_dual_ma.py"
        artifacts = [
            self._artifact("2026-07-17", 10.0),
            self._artifact("2026-07-20", 10.0),
            self._artifact("2026-07-21", 10.0),
            self._artifact("2026-07-22", 9.0),
            self._artifact("2026-07-23", 8.0),
            self._artifact("2026-07-24", 12.0),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = []
            for index, artifact in enumerate(artifacts):
                path = root / f"batch-{index}.json"
                path.write_text(json.dumps(artifact), encoding="utf-8")
                inputs.extend(["--input", str(path)])
            snapshot_path = root / "strategy.json"
            snapshot_path.write_text(json.dumps(self.snapshot), encoding="utf-8")
            output_path = root / "candidates.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    *inputs,
                    "--strategy-snapshot",
                    str(snapshot_path),
                    "--output",
                    str(output_path),
                    "--confirm-free-observation",
                ],
                cwd=BACKEND_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertFalse(saved["formal_use"])
            self.assertEqual(saved["candidates"][0]["would_action"], "BUY_OBSERVATION")
            self.assertFalse(saved["candidates"][0]["tradable"])
            repeated = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    *inputs,
                    "--strategy-snapshot",
                    str(snapshot_path),
                    "--output",
                    str(output_path),
                    "--confirm-free-observation",
                ],
                cwd=BACKEND_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(repeated.returncode, 2)
            self.assertIn("拒绝覆盖", repeated.stderr)
