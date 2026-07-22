import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path


os.environ.setdefault("SECRET_KEY", "p3-shadow-acceptance-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.shadow.contracts import (  # noqa: E402
    ImmutableReference,
    ProviderReference,
    ShadowContractError,
)
from app.shadow.test_execution import TestOnlyShadowRunner  # noqa: E402
from app.shadow.test_fixtures import TestOnlyFixtureProvider, test_only_now  # noqa: E402


class P3ShadowAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.cutoff = test_only_now()

    def test_interrupted_resume_is_deterministic_and_deduplicated(self):
        request = TestOnlyShadowRunner.build_request(information_cutoff=self.cutoff)
        first = TestOnlyShadowRunner().execute(run_id="test:interrupted", request=request)
        resumed = TestOnlyShadowRunner().execute(run_id="test:resumed", request=request)
        self.assertEqual(first.result_hash, resumed.result_hash)
        self.assertEqual(first.decision.decision_dedup_key, resumed.decision.decision_dedup_key)

    def test_unconfirmed_business_references_are_blocked(self):
        for label, reference in (
            ("P3_SAMPLE_UNCONFIRMED", ImmutableReference("", "a" * 64, test_only=True)),
            ("P3_STRATEGY_VERSION_UNCONFIRMED", ImmutableReference("", "b" * 64, test_only=True)),
            ("P3_INPUT_PROFILE_UNCONFIRMED", ImmutableReference("", "c" * 64, test_only=True)),
        ):
            with self.subTest(label=label):
                with self.assertRaises(ShadowContractError) as raised:
                    reference.validate(
                        label={
                            "P3_SAMPLE_UNCONFIRMED": "sample",
                            "P3_STRATEGY_VERSION_UNCONFIRMED": "strategy_version",
                            "P3_INPUT_PROFILE_UNCONFIRMED": "input_profile",
                        }[label],
                        data_mode="test",
                    )
                self.assertEqual(raised.exception.code, label)

    def test_test_data_cannot_be_replay_or_realtime(self):
        with self.assertRaises(ShadowContractError) as replay:
            ProviderReference(
                provider="test:provider", source="test:source", dataset_version="test-v1",
                license_evidence_ref="test-only", data_mode="replay", not_realtime=True,
            ).validate()
        self.assertEqual(replay.exception.code, "P3_TEST_REFERENCE_OUTSIDE_TEST_MODE")
        with self.assertRaises(ShadowContractError) as realtime:
            ProviderReference(
                provider="provider", source="source", dataset_version="v1",
                license_evidence_ref="evidence", data_mode="realtime", not_realtime=False,
            ).validate()
        self.assertEqual(realtime.exception.code, "P3_REALTIME_DATA_NOT_APPROVED")

    def test_all_fixture_failures_leave_no_success_result(self):
        request = TestOnlyShadowRunner.build_request(information_cutoff=self.cutoff)
        for scenario in ("missing", "stale", "hash_mismatch", "time_regression"):
            with self.subTest(scenario=scenario):
                with self.assertRaises(ShadowContractError):
                    TestOnlyShadowRunner(TestOnlyFixtureProvider(scenario=scenario)).execute(
                        run_id=f"test:{scenario}", request=request, max_age_seconds=60
                    )

    def test_future_data_after_cutoff_is_not_in_result_hash(self):
        request = TestOnlyShadowRunner.build_request(information_cutoff=self.cutoff)
        low = TestOnlyShadowRunner(TestOnlyFixtureProvider(future_close=-1.0)).execute(
            run_id="test:future-low", request=request
        )
        high = TestOnlyShadowRunner(TestOnlyFixtureProvider(future_close=1_000_000.0)).execute(
            run_id="test:future-high", request=request
        )
        self.assertEqual(low.result_hash, high.result_hash)
        self.assertEqual(low.decision.would_action, high.decision.would_action)

    def test_current_run_safety_evidence_is_all_zero(self):
        result = TestOnlyShadowRunner().execute(
            run_id="test:zero-effects",
            request=TestOnlyShadowRunner.build_request(information_cutoff=self.cutoff),
        )
        self.assertEqual(
            (
                result.safety.order_count,
                result.safety.order_service_calls,
                result.safety.execution_service_calls,
                result.safety.capital_write_count,
                result.safety.position_write_count,
            ),
            (0, 0, 0, 0, 0),
        )
        self.assertTrue(all(value is False for value in result.safety.release_locks_before.values()))
        self.assertTrue(all(value is False for value in result.safety.release_locks_after.values()))

    def test_shadow_module_has_no_order_or_network_dependencies(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (REPO_ROOT / "backend/app/shadow").glob("*.py")
        )
        for forbidden in ("app.trade", "simulation_trader", "live_trader", "httpx", "requests", "socket"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
