import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "local-single-operator-activation-test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.strategy.version_service import StrategyVersionError
from scripts.activate_local_single_operator_strategy import (
    _require_locks_closed,
    activation_request_hash,
)


class LocalSingleOperatorActivationTests(unittest.TestCase):
    def test_activation_request_hash_is_stable_and_snapshot_bound(self):
        common = {
            "actor_principal_id": "00000000-0000-0000-0000-000000000001",
            "strategy_id": 1,
            "source_version_id": 1,
            "source_params": {"fast_period": 5, "slow_period": 20, "position_pct": 0.2},
            "config_hash": "a" * 64,
            "catalog_hash": "b" * 64,
            "reason": "local single-operator activation",
        }
        self.assertEqual(activation_request_hash(**common), activation_request_hash(**common))
        self.assertNotEqual(
            activation_request_hash(**common),
            activation_request_hash(**{**common, "reason": "changed"}),
        )

    def test_activation_refuses_open_release_or_trading_lock(self):
        with patch.object(settings, "TRADING_EXECUTION_ENABLED", True):
            with self.assertRaises(StrategyVersionError) as rejected:
                _require_locks_closed()
        self.assertEqual(rejected.exception.code, "STRATEGY_LOCAL_ACTIVATION_LOCK_OPEN")

    def test_activation_command_uses_local_database_transaction_only(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "activate_local_single_operator_strategy.py"
        ).read_text(encoding="utf-8")
        self.assertIn("async with get_db() as db", source)
        self.assertNotIn("app.trade", source)
        self.assertNotIn("app.shadow", source)
        self.assertNotIn("Provider", source)
        self.assertNotIn("updated_at = NOW()", source)
        self.assertLess(
            source.index("prior = existing.mappings().first()"),
            source.index('if source["is_active"] is not False'),
        )


if __name__ == "__main__":
    unittest.main()
