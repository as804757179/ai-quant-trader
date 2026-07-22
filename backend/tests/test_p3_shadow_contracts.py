import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


os.environ.setdefault("SECRET_KEY", "p3-shadow-contract-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.shadow.contracts import (  # noqa: E402
    RELEASE_LOCK_KEYS,
    ImmutableReference,
    InputBatchReference,
    ProviderReference,
    RunSafetyAssertion,
    ShadowContractError,
    ShadowRunRequest,
)


NOW = datetime(2026, 7, 22, 9, 30, tzinfo=timezone.utc)


def _request(*, data_as_of: datetime = NOW) -> ShadowRunRequest:
    return ShadowRunRequest(
        data_mode="test",
        provider=ProviderReference(
            provider="test:fixture-provider",
            source="test:fixture-source",
            dataset_version="test-fixture-v1",
            license_evidence_ref="test-only",
            data_mode="test",
            not_realtime=True,
        ),
        sample=ImmutableReference("test:sample-v1", "a" * 64, test_only=True),
        strategy=ImmutableReference("test:strategy-v1", "b" * 64, test_only=True),
        input_profile=ImmutableReference("test:profile-v1", "c" * 64, test_only=True),
        input_batch=InputBatchReference(
            "test:batch-v1", "d" * 64, data_as_of, NOW - timedelta(seconds=1), NOW
        ),
        information_cutoff=NOW,
    )


def _safety(**changes) -> RunSafetyAssertion:
    locks = {key: False for key in RELEASE_LOCK_KEYS}
    payload = {
        "run_id": "test:run-v1",
        "tradable": False,
        "order_created": False,
        "order_count": 0,
        "order_service_calls": 0,
        "execution_service_calls": 0,
        "capital_write_count": 0,
        "position_write_count": 0,
        "release_locks_before": locks,
        "release_locks_after": dict(locks),
    }
    payload.update(changes)
    return RunSafetyAssertion(**payload)


class P3ShadowContractTests(unittest.TestCase):
    def test_test_only_request_is_valid(self):
        _request().validate()

    def test_test_mode_requires_explicit_test_only_references(self):
        request = _request()
        invalid = ShadowRunRequest(
            **{**request.__dict__, "sample": ImmutableReference("sample-v1", "a" * 64)}
        )
        with self.assertRaises(ShadowContractError) as raised:
            invalid.validate()
        self.assertEqual(raised.exception.code, "P3_TEST_ONLY_REFERENCE_REQUIRED")

    def test_future_data_is_rejected(self):
        with self.assertRaises(ShadowContractError) as raised:
            _request(data_as_of=NOW + timedelta(seconds=1)).validate()
        self.assertEqual(raised.exception.code, "P3_FUTURE_DATA_LEAK")

    def test_realtime_requires_explicit_approval(self):
        with self.assertRaises(ShadowContractError) as raised:
            ProviderReference(
                provider="provider", source="source", dataset_version="v1",
                license_evidence_ref="evidence", data_mode="realtime", not_realtime=False,
            ).validate()
        self.assertEqual(raised.exception.code, "P3_REALTIME_DATA_NOT_APPROVED")

    def test_safety_assertion_accepts_only_current_run_zero_effects(self):
        _safety().validate()
        with self.assertRaises(ShadowContractError) as raised:
            _safety(order_service_calls=1).validate()
        self.assertEqual(raised.exception.code, "P3_ZERO_ORDER_ASSERTION_FAILED")

    def test_safety_assertion_rejects_release_lock_change(self):
        after = {key: False for key in RELEASE_LOCK_KEYS}
        after["AI_ORDER_ENABLED"] = True
        with self.assertRaises(ShadowContractError) as raised:
            _safety(release_locks_after=after).validate()
        self.assertEqual(raised.exception.code, "P3_RELEASE_LOCK_CHANGED")


if __name__ == "__main__":
    unittest.main()
