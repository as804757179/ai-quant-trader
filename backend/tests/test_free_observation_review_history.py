from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "free-observation-review-history-test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://free-observation@localhost/unused")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/unused")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data.free_observation_review import FreeObservationReview  # noqa: E402
from app.data.free_observation_review_history import FreeObservationReviewHistory, FreeObservationReviewHistoryError  # noqa: E402


class FreeObservationReviewHistoryTests(TestCase):
    @staticmethod
    def _review(candidate_hash: str, action: str, outcome: str) -> dict[str, object]:
        item = {
            "stock_code": "000001.SZ", "would_action": action, "baseline_trade_date": "20260722",
            "realization_trade_date": "20260723", "close_change_pct": 1.0, "outcome": outcome,
            "observation_only": True, "tradable": False, "order_created": False,
        }
        return {
            "data_mode": "free_observation", "data_qualification": "unverified", "formal_use": False,
            "candidate_result_hash": candidate_hash, "review_items": [item],
            "review_hash": FreeObservationReview._hash({"candidate_result_hash": candidate_hash, "review_items": [item]}),
        }

    def test_summarizes_observation_statistics_without_optimization(self) -> None:
        first = self._review("a" * 64, "BUY_OBSERVATION", "DIRECTION_MATCHED")
        second = self._review("b" * 64, "BUY_OBSERVATION", "DIRECTION_MISSED")
        report = FreeObservationReviewHistory.summarize(review_documents=[first, second])
        self.assertEqual(report["direction_summary"]["BUY_OBSERVATION"], {"matched": 1, "missed": 1, "pending": 0, "unscored": 0, "scored": 2, "direction_match_rate": 0.5})
        self.assertEqual(report["optimization_status"], "blocked")
        self.assertEqual(report["parameter_change_candidates"], [])
        self.assertFalse(report["formal_use"])
        self.assertFalse(report["tradable"])

    def test_rejects_duplicate_candidate_and_hash_mismatch(self) -> None:
        review = self._review("a" * 64, "BUY_OBSERVATION", "DIRECTION_MATCHED")
        with self.assertRaises(FreeObservationReviewHistoryError) as duplicate:
            FreeObservationReviewHistory.summarize(review_documents=[review, review])
        self.assertEqual(duplicate.exception.code, "FREE_OBSERVATION_REVIEW_HISTORY_DUPLICATE")
        broken = dict(review)
        broken["review_hash"] = "0" * 64
        with self.assertRaises(FreeObservationReviewHistoryError) as invalid:
            FreeObservationReviewHistory.summarize(review_documents=[broken])
        self.assertEqual(invalid.exception.code, "FREE_OBSERVATION_REVIEW_HISTORY_HASH_MISMATCH")

    def test_command_writes_new_file_and_refuses_production(self) -> None:
        script = BACKEND_ROOT / "scripts" / "summarize_free_observation_reviews.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review_path, output_path = root / "review.json", root / "summary.json"
            review_path.write_text(json.dumps(self._review("a" * 64, "BUY_OBSERVATION", "DIRECTION_MATCHED")), encoding="utf-8")
            command = [sys.executable, str(script), "--review", str(review_path), "--output", str(output_path), "--confirm-free-observation"]
            result = subprocess.run(command, cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["optimization_status"], "blocked")
            repeated = subprocess.run(command, cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(repeated.returncode, 2)
            environment = dict(os.environ)
            environment["APP_ENV"] = "production"
            production = subprocess.run(command, cwd=BACKEND_ROOT, env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(production.returncode, 2)
