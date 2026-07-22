from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
import unittest

import httpx


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "free-observation-test-secret-key-32chars")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://free-observation@localhost/unused")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/unused")

from app.data.tushare_free_observation import (  # noqa: E402
    FREE_OBSERVATION_MODE,
    FreeObservationError,
    TushareFreeObservationClient,
)


class TushareFreeObservationTests(unittest.TestCase):
    def _client(self, payload: dict[str, object]) -> TushareFreeObservationClient:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        return TushareFreeObservationClient(
            token="test-token",
            client=httpx.Client(transport=transport),
        )

    def test_requires_token(self) -> None:
        with self.assertRaisesRegex(FreeObservationError, "Tushare Token"):
            TushareFreeObservationClient(token="")

    def test_daily_batch_is_unverified_and_hashable(self) -> None:
        payload = {
            "code": 0,
            "data": {
                "fields": ["ts_code", "trade_date", "open", "high", "low", "close", "vol"],
                "items": [["000001.SZ", "20260722", 10.0, 10.5, 9.9, 10.2, 1000]],
            },
        }
        first = self._client(payload).fetch_daily(trade_date=date(2026, 7, 22))
        second = self._client(payload).fetch_daily(trade_date=date(2026, 7, 22))
        self.assertEqual(first.data_mode, FREE_OBSERVATION_MODE)
        self.assertEqual(first.data_qualification, "unverified")
        self.assertFalse(first.formal_use)
        self.assertIsNone(first.available_at)
        self.assertEqual(first.available_at_status, "unverified")
        self.assertEqual(first.lineage_status, "unverified")
        self.assertEqual(first.batch_hash, second.batch_hash)
        self.assertEqual(first.rows[0]["row_hash"], second.rows[0]["row_hash"])
        manifest = first.as_dict()["universe_manifest"]
        self.assertEqual(manifest["scope"], "provider_response_rows_for_trade_date")
        self.assertEqual(manifest["coverage_status"], "unverified")
        self.assertEqual(manifest["returned_row_count"], 1)
        self.assertEqual(len(manifest["stock_code_hash"]), 64)
        self.assertIn("all_a_share_coverage", manifest["not_proven"])
        self.assertEqual(first.as_dict()["blocked_from"], ["certified_store", "formal_p3", "formal_p4", "p5", "trade_execution"])

    def test_rejects_provider_error_and_invalid_row(self) -> None:
        rejected = self._client({"code": 2002, "msg": "permission denied", "data": {}})
        with self.assertRaisesRegex(FreeObservationError, "拒绝请求"):
            rejected.fetch_daily(trade_date=date(2026, 7, 22))
        invalid = self._client({"code": 0, "data": {"fields": ["ts_code"], "items": [["000001.SZ"]]}})
        with self.assertRaisesRegex(FreeObservationError, "缺少必要 OHLC"):
            invalid.fetch_daily(trade_date=date(2026, 7, 22))

    def test_rejects_wrong_trade_date_and_duplicate_stock_rows(self) -> None:
        fields = ["ts_code", "trade_date", "open", "high", "low", "close"]
        wrong_date = self._client({"code": 0, "data": {"fields": fields, "items": [["000001.SZ", "20260721", 10, 10, 10, 10]]}})
        with self.assertRaises(FreeObservationError) as date_error:
            wrong_date.fetch_daily(trade_date=date(2026, 7, 22))
        self.assertEqual(date_error.exception.code, "FREE_OBSERVATION_TRADE_DATE_MISMATCH")
        duplicate = self._client({"code": 0, "data": {"fields": fields, "items": [["000001.SZ", "20260722", 10, 10, 10, 10], ["000001.SZ", "20260722", 11, 11, 11, 11]]}})
        with self.assertRaises(FreeObservationError) as duplicate_error:
            duplicate.fetch_daily(trade_date=date(2026, 7, 22))
        self.assertEqual(duplicate_error.exception.code, "FREE_OBSERVATION_ROW_DUPLICATE")

    def test_command_requires_confirmation_and_never_overwrites(self) -> None:
        script = BACKEND_ROOT / "scripts" / "fetch_free_observation_daily.py"
        base = [sys.executable, str(script), "--trade-date", "2026-07-22", "--output", "unused.json"]
        missing_confirmation = subprocess.run(
            base, cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=30
        )
        self.assertEqual(missing_confirmation.returncode, 2)
        self.assertIn("--confirm-free-observation", missing_confirmation.stderr)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "daily.json"
            env = dict(os.environ)
            env.pop("TUSHARE_TOKEN", None)
            missing_token = subprocess.run(
                [*base[:-1], str(output), "--confirm-free-observation"],
                cwd=BACKEND_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(missing_token.returncode, 1)
            self.assertIn("FREE_OBSERVATION_TOKEN_REQUIRED", missing_token.stderr)
            self.assertFalse(output.exists())

    def test_command_rejects_production_before_provider_access(self) -> None:
        script = BACKEND_ROOT / "scripts" / "fetch_free_observation_daily.py"
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ)
            environment["APP_ENV"] = "production"
            environment["TUSHARE_TOKEN"] = "must-not-be-used"
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--trade-date",
                    "2026-07-22",
                    "--output",
                    str(Path(directory) / "daily.json"),
                    "--confirm-free-observation",
                ],
                cwd=BACKEND_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("拒绝 production", result.stderr)


if __name__ == "__main__":
    unittest.main()
