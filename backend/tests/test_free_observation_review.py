from __future__ import annotations

import os
import sys
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import TestCase

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "free-observation-review-test-secret-key-32chars")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://free-observation@localhost/unused")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/unused")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data.free_observation_dual_ma import FreeObservationDualMaEvaluator  # noqa: E402
from app.data.free_observation_review import FreeObservationReview, FreeObservationReviewError  # noqa: E402
from app.data.tushare_free_observation import TUSHARE_DATASET_VERSION, TUSHARE_PROVIDER, TUSHARE_SOURCE  # noqa: E402
from app.strategy.version_service import StrategyVersionService  # noqa: E402


class FreeObservationReviewTests(TestCase):
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

    def test_reviews_direction_without_portfolio_or_order(self) -> None:
        input_artifacts = [
            self._artifact("2026-07-17", 10.0), self._artifact("2026-07-20", 10.0),
            self._artifact("2026-07-21", 10.0), self._artifact("2026-07-22", 9.0),
            self._artifact("2026-07-23", 8.0), self._artifact("2026-07-24", 12.0),
        ]
        candidate = FreeObservationDualMaEvaluator.evaluate(artifacts=input_artifacts, strategy_snapshot=self.snapshot).as_dict()
        report = FreeObservationReview.evaluate(candidate_document=candidate, artifacts=[*input_artifacts, self._artifact("2026-07-25", 13.0)])
        item = report["review_items"][0]
        self.assertEqual(item["outcome"], "DIRECTION_MATCHED")
        self.assertGreater(item["close_change_pct"], 0)
        self.assertFalse(item["tradable"])
        self.assertFalse(item["order_created"])
        self.assertFalse(report["formal_use"])
        self.assertEqual(report["research_readiness"], "not_granted")

    def test_rejects_hash_mismatch_and_missing_candidate_input(self) -> None:
        artifact = self._artifact("2026-07-22", 10.0)
        candidate = FreeObservationDualMaEvaluator.evaluate(artifacts=[artifact], strategy_snapshot=self.snapshot).as_dict()
        candidate["result_hash"] = "0" * 64
        with self.assertRaisesRegex(FreeObservationReviewError, "结果 Hash"):
            FreeObservationReview.evaluate(candidate_document=candidate, artifacts=[artifact])
        candidate = FreeObservationDualMaEvaluator.evaluate(artifacts=[artifact], strategy_snapshot=self.snapshot).as_dict()
        with self.assertRaisesRegex(FreeObservationReviewError, "批次缺失"):
            FreeObservationReview.evaluate(candidate_document=candidate, artifacts=[self._artifact("2026-07-23", 11.0)])

    def test_keeps_realization_pending_when_later_trade_date_was_fetched_before_candidate(self) -> None:
        input_artifacts = [
            self._artifact("2026-07-17", 10.0), self._artifact("2026-07-20", 10.0),
            self._artifact("2026-07-21", 10.0), self._artifact("2026-07-22", 9.0),
            self._artifact("2026-07-23", 8.0), self._artifact("2026-07-24", 12.0),
        ]
        input_artifacts[-1]["fetched_at"] = datetime(2026, 7, 30, 15, 5, tzinfo=timezone.utc).isoformat()
        candidate = FreeObservationDualMaEvaluator.evaluate(artifacts=input_artifacts, strategy_snapshot=self.snapshot).as_dict()
        report = FreeObservationReview.evaluate(
            candidate_document=candidate,
            artifacts=[*input_artifacts, self._artifact("2026-07-25", 13.0)],
        )
        self.assertEqual(report["review_items"][0]["outcome"], "REALIZATION_PENDING")

    def test_command_writes_new_review_file_and_rejects_production(self) -> None:
        input_artifacts = [
            self._artifact("2026-07-17", 10.0), self._artifact("2026-07-20", 10.0),
            self._artifact("2026-07-21", 10.0), self._artifact("2026-07-22", 9.0),
            self._artifact("2026-07-23", 8.0), self._artifact("2026-07-24", 12.0),
        ]
        candidate = FreeObservationDualMaEvaluator.evaluate(artifacts=input_artifacts, strategy_snapshot=self.snapshot).as_dict()
        artifacts = [*input_artifacts, self._artifact("2026-07-25", 13.0)]
        script = BACKEND_ROOT / "scripts" / "review_free_observation_candidates.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_path = root / "candidate.json"
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            artifact_args = []
            for index, artifact in enumerate(artifacts):
                path = root / f"artifact-{index}.json"
                path.write_text(json.dumps(artifact), encoding="utf-8")
                artifact_args.extend(["--artifact", str(path)])
            output_path = root / "review.json"
            command = [
                sys.executable, str(script), "--candidate", str(candidate_path), *artifact_args,
                "--output", str(output_path), "--confirm-free-observation",
            ]
            result = subprocess.run(command, cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["review_items"][0]["outcome"], "DIRECTION_MATCHED")
            repeated = subprocess.run(command, cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(repeated.returncode, 2)
            environment = dict(os.environ)
            environment["APP_ENV"] = "production"
            production = subprocess.run(command, cwd=BACKEND_ROOT, env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(production.returncode, 2)
            self.assertIn("拒绝 production", production.stderr)
