import asyncio
import os
import unittest
from unittest.mock import patch

os.environ["SECRET_KEY"] = "l2-fuse-test-secret"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"

from app.risk.fuse import (  # noqa: E402
    FUSE_CACHE_VERSION,
    FUSE_STATUS_VERSION,
    FuseManager,
)
from app.api import risk as risk_api  # noqa: E402


class Result:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class FakeDb:
    def __init__(self, value=None, error: Exception | None = None):
        self.value = value
        self.error = error

    async def execute(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return Result(self.value)


class FakeCache:
    def __init__(self, value=None, error: Exception | None = None):
        self.value = value
        self.error = error

    async def get_raw_strict(self, _key):
        if self.error:
            raise self.error
        return self.value

    async def set_raw_strict(self, _key, value, _ttl=None):
        if self.error:
            raise self.error
        self.value = value

    async def delete_raw_strict(self, _key):
        if self.error:
            raise self.error
        self.value = None


class FakeDbContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return False


def run(coro):
    return asyncio.run(coro)


class FuseFailClosedTests(unittest.TestCase):
    def test_dependency_and_cache_failures_are_fused(self):
        self.assertTrue(run(FuseManager(FakeDb(error=RuntimeError()), FakeCache()).is_fused("live")))
        self.assertTrue(run(FuseManager(FakeDb(), FakeCache(error=RuntimeError())).is_fused("live")))
        self.assertTrue(run(FuseManager(FakeDb(), FakeCache("not-json")).is_fused("live")))

    def test_only_verified_inactive_db_and_empty_cache_are_unfused(self):
        self.assertFalse(run(FuseManager(FakeDb(), FakeCache()).is_fused("simulation")))

    def test_active_or_stale_cache_remains_fused(self):
        active_cache = (
            f'{{"version": {FUSE_CACHE_VERSION}, "active": true, "reason": "test"}}'
        )
        self.assertTrue(run(FuseManager(FakeDb("1"), FakeCache()).is_fused("live")))
        self.assertTrue(run(FuseManager(FakeDb(), FakeCache(active_cache)).is_fused("live")))

    def test_state_snapshot_distinguishes_active_from_safe_blocked_uncertainty(self):
        db_failure = run(FuseManager(FakeDb(error=RuntimeError()), FakeCache()).get_state("live"))
        self.assertTrue(db_failure["is_active"])
        self.assertEqual(db_failure["status"], "blocked_unknown")
        self.assertEqual(db_failure["reason"], "db_unavailable")
        self.assertEqual(db_failure["status_version"], FUSE_STATUS_VERSION)

        active = run(FuseManager(FakeDb("1"), FakeCache()).get_state("live"))
        self.assertTrue(active["is_active"])
        self.assertEqual(active["status"], "active")

        inconsistent = run(
            FuseManager(
                FakeDb(),
                FakeCache(f'{{"version": {FUSE_CACHE_VERSION}, "active": true}}'),
            ).get_state("live")
        )
        self.assertTrue(inconsistent["is_active"])
        self.assertEqual(inconsistent["status"], "blocked_inconsistent")
        self.assertEqual(inconsistent["reason"], "cache_active_while_db_inactive")

    def test_status_endpoint_exposes_database_uncertainty_as_blocked(self):
        with (
            patch(
                "app.api.risk.get_db",
                return_value=FakeDbContext(FakeDb(error=RuntimeError())),
            ),
            patch("app.api.risk.CacheManager", return_value=FakeCache()),
        ):
            response = run(risk_api.get_fuse_status(mode="live"))

        self.assertTrue(response.data["is_active"])
        self.assertEqual(response.data["status"], "blocked_unknown")
        self.assertEqual(response.data["reason"], "db_unavailable")
        self.assertEqual(response.data["status_version"], FUSE_STATUS_VERSION)
        self.assertEqual(response.data["history_status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
