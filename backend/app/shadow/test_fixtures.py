from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal


TEST_FIXTURE_GENERATOR_VERSION = "p3-shadow-test-fixture-v1"
TEST_ONLY_PROVIDER = "test:p3-shadow-fixture-provider"
TEST_ONLY_SOURCE = "test:p3-shadow-fixture-source"
TEST_ONLY_LICENSE_EVIDENCE = "test-only"
TEST_ONLY_STOCK_CODE = "TEST:000001"


@dataclass(frozen=True)
class TestOnlyBar:
    available_at: datetime
    close: float


@dataclass(frozen=True)
class TestOnlyFixtureBatch:
    bars: tuple[TestOnlyBar, ...]
    fetched_at: datetime
    received_at: datetime
    content_hash: str


class TestOnlyFixtureProvider:
    """Deterministic in-process fixture provider with no network capability."""

    def __init__(
        self,
        *,
        scenario: Literal["normal", "missing", "stale", "hash_mismatch", "time_regression"] = "normal",
        future_close: float = 999.0,
    ) -> None:
        self.scenario = scenario
        self.future_close = future_close
        self.network_request_count = 0

    def load(self, *, information_cutoff: datetime) -> TestOnlyFixtureBatch:
        base = information_cutoff - timedelta(minutes=2)
        bars = (
            TestOnlyBar(base, 10.0),
            TestOnlyBar(base + timedelta(minutes=1), 10.5),
            TestOnlyBar(information_cutoff + timedelta(minutes=1), self.future_close),
        )
        if self.scenario == "missing":
            bars = ()
        fetched_at = information_cutoff - timedelta(seconds=2)
        received_at = information_cutoff - timedelta(seconds=1)
        if self.scenario == "time_regression":
            fetched_at, received_at = received_at, fetched_at
        content_hash = self._hash(bars)
        if self.scenario == "hash_mismatch":
            content_hash = "0" * 64
        if self.scenario == "stale":
            bars = tuple(
                TestOnlyBar(item.available_at - timedelta(hours=1), item.close)
                for item in bars
            )
            content_hash = self._hash(bars)
        return TestOnlyFixtureBatch(bars, fetched_at, received_at, content_hash)

    @staticmethod
    def _hash(bars: tuple[TestOnlyBar, ...]) -> str:
        payload = [
            {"available_at": item.available_at.isoformat(), "close": item.close}
            for item in bars
        ]
        return hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def verify(batch: TestOnlyFixtureBatch) -> bool:
        return batch.content_hash == TestOnlyFixtureProvider._hash(batch.bars)


def test_only_reference_hash(value: str) -> str:
    return hashlib.sha256(
        f"{TEST_FIXTURE_GENERATOR_VERSION}:{value}".encode("utf-8")
    ).hexdigest()


def test_only_now() -> datetime:
    return datetime(2026, 7, 22, 9, 30, tzinfo=timezone.utc)
