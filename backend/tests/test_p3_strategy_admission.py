import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "p3-admission-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.strategy.admission_service import StrategyAdmissionService
from app.strategy.version_service import StrategyVersionError, StrategyVersionService


class P3StrategyAdmissionTests(unittest.TestCase):
    def test_missing_activation_fails_closed(self):
        now = datetime.now(timezone.utc)
        with self.assertRaises(StrategyVersionError) as raised:
            StrategyAdmissionService.resolve(strategy_type="dual_ma", subjects=[{"id": 1, "strategy_type": "dual_ma", "is_active": True}], snapshot=None, validity_events=[], as_of=now)
        self.assertEqual(raised.exception.code, "P3_STRATEGY_VERSION_UNCONFIRMED")

    def test_inactive_and_multiple_subjects_fail_closed(self):
        now = datetime.now(timezone.utc)
        for subjects in ([{"id": 1, "strategy_type": "dual_ma", "is_active": False}], [{"id": 1, "strategy_type": "dual_ma", "is_active": True}, {"id": 2, "strategy_type": "dual_ma", "is_active": True}]):
            with self.assertRaises(StrategyVersionError):
                StrategyAdmissionService.resolve(strategy_type="dual_ma", subjects=subjects, snapshot=None, validity_events=[], as_of=now)

    def test_revoked_or_expired_event_fails_closed(self):
        now = datetime.now(timezone.utc)
        catalog_hash = StrategyVersionService.catalog_hash("dual_ma")
        params = {"fast_period": 5, "slow_period": 20, "position_pct": 0.2}
        snapshot = {"version_id": 1, "active_version_id": 1, "approval_status": "approved", "enabled": True, "params": params, "catalog_hash": catalog_hash, "config_hash": StrategyVersionService.config_hash(strategy_type="dual_ma", enabled=True, params=params, catalog_hash=catalog_hash)}
        events = [{"event_type": "activated", "effective_at": now - timedelta(days=1), "valid_until": now + timedelta(days=1)}, {"event_type": "revoked", "effective_at": now, "valid_until": None}]
        with self.assertRaises(StrategyVersionError):
            StrategyAdmissionService.resolve(strategy_type="dual_ma", subjects=[{"id": 1, "strategy_type": "dual_ma", "is_active": True}], snapshot=snapshot, validity_events=events, as_of=now)


if __name__ == "__main__":
    unittest.main()
