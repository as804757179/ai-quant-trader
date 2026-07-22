from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal


TEST_FIXTURE_GENERATOR_VERSION = "p3-shadow-test-fixture-v1"
TEST_ONLY_FIXTURE_KIND = "synthetic/test-only"
TEST_ONLY_PROVIDER = "test:p3-shadow-fixture-provider"
TEST_ONLY_SOURCE = "test:p3-shadow-fixture-source"
TEST_ONLY_LICENSE_EVIDENCE = "test-only"
TEST_ONLY_STOCK_CODE = "TEST:000001"
TEST_ONLY_MANIFEST_ID = "test:p3-shadow-manifest-v1"
TEST_ONLY_STRATEGY_PARAMETERS = (
    ("fast_period", 5),
    ("slow_period", 20),
    ("position_pct", 0.2),
)


@dataclass(frozen=True)
class TestOnlyBar:
    trading_at: datetime
    available_at: datetime | None
    close: float
    row_hash: str
    lineage_ref: str


@dataclass(frozen=True)
class TestOnlyFixtureBatch:
    bars: tuple[TestOnlyBar, ...]
    fetched_at: datetime
    received_at: datetime
    content_hash: str
    manifest_id: str
    manifest_hash: str
    fixture_kind: str


class TestOnlyFixtureProvider:
    """Deterministic in-process fixture provider with no network capability."""

    def __init__(
        self,
        *,
        scenario: Literal[
            "normal", "missing", "stale", "hash_mismatch", "time_regression",
            "available_at_missing", "lineage_missing", "row_hash_mismatch", "duplicate",
            "row_time_regression", "manifest_hash_mismatch",
        ] = "normal",
        future_close: float = 999.0,
    ) -> None:
        self.scenario = scenario
        self.future_close = future_close
        self.network_request_count = 0

    def load(self, *, information_cutoff: datetime) -> TestOnlyFixtureBatch:
        base = information_cutoff - timedelta(minutes=2)
        bars = (
            self._bar(base, 10.0, "test:lineage:1"),
            self._bar(base + timedelta(minutes=1), 10.5, "test:lineage:2"),
            self._bar(information_cutoff + timedelta(minutes=1), self.future_close, "test:lineage:3"),
        )
        if self.scenario == "missing":
            bars = ()
        fetched_at = information_cutoff - timedelta(seconds=2)
        received_at = information_cutoff - timedelta(seconds=1)
        if self.scenario == "time_regression":
            fetched_at, received_at = received_at, fetched_at
        if self.scenario == "stale":
            bars = tuple(
                self._bar(item.trading_at - timedelta(hours=1), item.close, item.lineage_ref)
                for item in bars
            )
        if self.scenario == "available_at_missing":
            item = bars[0]
            bars = (TestOnlyBar(item.trading_at, None, item.close, item.row_hash, item.lineage_ref), *bars[1:])
        if self.scenario == "lineage_missing":
            item = bars[0]
            bars = (TestOnlyBar(item.trading_at, item.available_at, item.close, item.row_hash, ""), *bars[1:])
        if self.scenario == "row_hash_mismatch":
            item = bars[0]
            bars = (TestOnlyBar(item.trading_at, item.available_at, item.close, "0" * 64, item.lineage_ref), *bars[1:])
        if self.scenario == "duplicate":
            bars = (bars[0], bars[1], bars[1], bars[2])
        if self.scenario == "row_time_regression":
            bars = (bars[1], bars[0], bars[2])
        content_hash = self._hash(bars)
        if self.scenario == "hash_mismatch":
            content_hash = "0" * 64
        manifest_hash = self._manifest_hash()
        if self.scenario == "manifest_hash_mismatch":
            manifest_hash = "0" * 64
        return TestOnlyFixtureBatch(
            bars, fetched_at, received_at, content_hash, TEST_ONLY_MANIFEST_ID,
            manifest_hash, TEST_ONLY_FIXTURE_KIND,
        )

    @staticmethod
    def _bar(trading_at: datetime, close: float, lineage_ref: str) -> TestOnlyBar:
        available_at = trading_at
        row_hash = TestOnlyFixtureProvider._row_hash(trading_at, available_at, close)
        return TestOnlyBar(trading_at, available_at, close, row_hash, lineage_ref)

    @staticmethod
    def _hash(bars: tuple[TestOnlyBar, ...]) -> str:
        payload = [
            {
                "trading_at": item.trading_at.isoformat(),
                "available_at": item.available_at.isoformat() if item.available_at else None,
                "close": item.close,
                "row_hash": item.row_hash,
                "lineage_ref": item.lineage_ref,
            }
            for item in bars
        ]
        return hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _row_hash(trading_at: datetime, available_at: datetime | None, close: float) -> str:
        payload = {
            "fixture_kind": TEST_ONLY_FIXTURE_KIND,
            "generator_version": TEST_FIXTURE_GENERATOR_VERSION,
            "trading_at": trading_at.isoformat(),
            "available_at": available_at.isoformat() if available_at else None,
            "close": close,
        }
        return hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _manifest_hash() -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "fixture_kind": TEST_ONLY_FIXTURE_KIND,
                    "generator_version": TEST_FIXTURE_GENERATOR_VERSION,
                    "manifest_id": TEST_ONLY_MANIFEST_ID,
                    "provider": TEST_ONLY_PROVIDER,
                    "source": TEST_ONLY_SOURCE,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
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
