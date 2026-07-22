from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "free-observation-strategy-snapshot-test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://free-observation@localhost/unused")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/unused")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data.free_observation_strategy_snapshot import (  # noqa: E402
    FreeObservationStrategySnapshotError,
    FreeObservationStrategySnapshotExporter,
)
from app.strategy.version_service import StrategyVersionService  # noqa: E402


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _ReadOnlyDb:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""

    async def execute(self, statement, _params):
        self.sql = str(statement)
        return _Result(self.rows)


class FreeObservationStrategySnapshotTests(TestCase):
    @staticmethod
    def _row(**changes):
        params = {"fast_period": 2, "slow_period": 5, "position_pct": 0.2}
        catalog_hash = StrategyVersionService.catalog_hash("dual_ma")
        row = {
            "strategy_id": 1, "strategy_type": "dual_ma", "is_active": True, "revision": 5,
            "active_version_id": 5, "version_id": 5, "version_number": 5, "enabled": True,
            "params": params, "catalog_hash": catalog_hash,
            "config_hash": StrategyVersionService.config_hash(strategy_type="dual_ma", enabled=True, params=params, catalog_hash=catalog_hash),
            "approval_status": "approved",
        }
        return {**row, **changes}

    def test_exports_verified_immutable_snapshot_with_read_only_query(self) -> None:
        db = _ReadOnlyDb([self._row()])
        snapshot = asyncio.run(FreeObservationStrategySnapshotExporter().export(db))
        self.assertEqual(snapshot["version"], 5)
        self.assertTrue(snapshot["enabled"])
        self.assertEqual(len(snapshot["snapshot_hash"]), 64)
        self.assertFalse(snapshot["formal_use"])
        self.assertNotIn("INSERT", db.sql.upper())
        self.assertNotIn("UPDATE", db.sql.upper())
        self.assertNotIn("DELETE", db.sql.upper())

    def test_rejects_non_unique_or_invalid_active_version(self) -> None:
        with self.assertRaises(FreeObservationStrategySnapshotError) as multiple:
            asyncio.run(FreeObservationStrategySnapshotExporter().export(_ReadOnlyDb([self._row(), self._row(strategy_id=2)])))
        self.assertEqual(multiple.exception.code, "FREE_OBSERVATION_STRATEGY_UNCONFIRMED")
        with self.assertRaises(FreeObservationStrategySnapshotError) as invalid:
            asyncio.run(FreeObservationStrategySnapshotExporter().export(_ReadOnlyDb([self._row(config_hash="0" * 64)])))
        self.assertEqual(invalid.exception.code, "FREE_OBSERVATION_STRATEGY_UNCONFIRMED")

    def test_command_refuses_production_before_database_access(self) -> None:
        script = BACKEND_ROOT / "scripts" / "export_free_observation_strategy_snapshot.py"
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ)
            environment["APP_ENV"] = "production"
            result = subprocess.run(
                [sys.executable, str(script), "--output", str(Path(directory) / "snapshot.json"), "--confirm-free-observation"],
                cwd=BACKEND_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    import unittest

    unittest.main()
