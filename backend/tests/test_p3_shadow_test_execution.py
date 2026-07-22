import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("SECRET_KEY", "p3-shadow-test-execution-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import settings  # noqa: E402
from app.shadow.contracts import ShadowContractError  # noqa: E402
from app.shadow.test_execution import TestOnlyShadowRunner  # noqa: E402
from app.shadow.test_fixtures import TestOnlyFixtureProvider, test_only_now  # noqa: E402


class P3ShadowTestExecutionTests(unittest.TestCase):
    def setUp(self):
        self.cutoff = test_only_now()

    def test_deterministic_result_and_zero_side_effects(self):
        runner = TestOnlyShadowRunner()
        request = runner.build_request(information_cutoff=self.cutoff)
        first = runner.execute(run_id="test:run-1", request=request)
        retried = runner.execute(run_id="test:run-2", request=request)
        self.assertEqual(first.result_hash, retried.result_hash)
        self.assertEqual(first.decision.decision_dedup_key, retried.decision.decision_dedup_key)
        self.assertEqual(first.data_mode, "test")
        self.assertTrue(first.not_realtime)
        self.assertEqual(first.network_request_count, 0)
        self.assertEqual(first.safety.order_count, 0)
        self.assertEqual(first.safety.order_service_calls, 0)
        self.assertEqual(first.safety.execution_service_calls, 0)
        self.assertEqual(first.safety.capital_write_count, 0)
        self.assertEqual(first.safety.position_write_count, 0)
        self.assertFalse(first.safety.tradable)
        self.assertFalse(first.safety.order_created)
        self.assertTrue(all(value is False for value in first.safety.release_locks_before.values()))
        self.assertTrue(all(value is False for value in first.safety.release_locks_after.values()))

    def test_future_fixture_data_does_not_change_decision(self):
        request = TestOnlyShadowRunner.build_request(information_cutoff=self.cutoff)
        baseline = TestOnlyShadowRunner(TestOnlyFixtureProvider(future_close=999.0)).execute(
            run_id="test:run-1", request=request
        )
        later = TestOnlyShadowRunner(TestOnlyFixtureProvider(future_close=1_000_000.0)).execute(
            run_id="test:run-2", request=request
        )
        self.assertEqual(baseline.decision.evidence_hash, later.decision.evidence_hash)
        self.assertEqual(baseline.decision.would_action, later.decision.would_action)

    def test_fixture_failure_modes_fail_closed(self):
        request = TestOnlyShadowRunner.build_request(information_cutoff=self.cutoff)
        cases = (
            ("missing", "P3_DATA_UNAVAILABLE"),
            ("stale", "P3_DATA_STALE"),
            ("hash_mismatch", "P3_INPUT_HASH_MISMATCH"),
            ("time_regression", "P3_INPUT_TIME_REGRESSION"),
        )
        for scenario, expected_code in cases:
            with self.subTest(scenario=scenario):
                with self.assertRaises(ShadowContractError) as raised:
                    TestOnlyShadowRunner(TestOnlyFixtureProvider(scenario=scenario)).execute(
                        run_id=f"test:{scenario}", request=request, max_age_seconds=60
                    )
                self.assertEqual(raised.exception.code, expected_code)

    def test_test_runner_rejects_non_test_mode(self):
        request = TestOnlyShadowRunner.build_request(information_cutoff=self.cutoff)
        invalid = request.__class__(**{**request.__dict__, "data_mode": "replay"})
        with self.assertRaises(ShadowContractError) as raised:
            TestOnlyShadowRunner().execute(run_id="test:run", request=invalid)
        self.assertEqual(raised.exception.code, "P3_TEST_EXECUTION_ONLY")

    def test_open_release_lock_fails_closed(self):
        request = TestOnlyShadowRunner.build_request(information_cutoff=self.cutoff)
        with patch.object(settings, "AI_ORDER_ENABLED", True):
            with self.assertRaises(ShadowContractError) as raised:
                TestOnlyShadowRunner().execute(run_id="test:run", request=request)
        self.assertEqual(raised.exception.code, "P3_RELEASE_LOCK_CHANGED")

    def test_fixture_uses_no_network_client_import(self):
        for path in (
            REPO_ROOT / "backend/app/shadow/test_fixtures.py",
            REPO_ROOT / "backend/app/shadow/test_execution.py",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("httpx", source)
            self.assertNotIn("requests", source)
            self.assertNotIn("socket", source)


if __name__ == "__main__":
    unittest.main()
