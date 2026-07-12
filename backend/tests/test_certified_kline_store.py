from __future__ import annotations

import asyncio
import inspect
from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.backtest.service import BacktestService
from app.data.certified_kline_repository import CertifiedKlineRepository
from app.data.certified_store_writer import CertifiedStoreWriter
from app.data.kline_contract import KlineContract
from app.data.research_profiles import ResearchDataRequirementProfile
from app.screener.engine import ScreenerEngine


def test_kline_contract_canonical_semantics_and_units() -> None:
    row = KlineContract.normalize_sohu_row(
        "300308",
        ["2026-06-01", "10", "11", "1", "10", "9", "12", "123", "45.6", "2.5%"],
    )
    assert row["stock_code"] == "300308.SZ"
    assert row["exchange"] == "SZ"
    assert row["time"].isoformat() == "2026-06-01T15:00:00+08:00"
    assert row["volume"] == 12_300
    assert row["amount"] == 456_000
    assert row["adjustment"] == "raw"
    assert row["price_currency"] == row["amount_unit"] == "CNY"
    assert row["volume_unit"] == "share"


def test_kline_contract_prevents_duplicate_unit_conversion() -> None:
    assert KlineContract.volume_to_shares(123, "share") == 123
    assert KlineContract.amount_to_cny(456, "CNY") == 456
    with pytest.raises(ValueError):
        KlineContract.volume_to_shares(123, "unknown")


def test_repository_requires_explicit_adjustment() -> None:
    repository = CertifiedKlineRepository()
    with pytest.raises(TypeError):
        repository.get_bars(["300308.SZ"], period="1d")
    with pytest.raises(ValueError):
        asyncio.run(
            repository.get_bars(
                ["300308.SZ"], period="1d", adjustment="unknown"
            )
        )


def test_active_consumers_use_only_certified_repository() -> None:
    for method in (
        BacktestService._load_bars,
        ScreenerEngine._load_universe,
    ):
        source = inspect.getsource(method)
        assert "kline_repository" in source
        assert "market.klines" not in source
        assert "kline_provenance" not in source


def test_backtest_maps_full_symbol_without_querying_legacy() -> None:
    repository = AsyncMock()
    repository.assert_dataset_ready = AsyncMock()
    repository.get_bars_for_profile = AsyncMock(return_value=[
        {
            "stock_code": "300308.SZ",
            "trading_date": date(2026, 6, 1),
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10.5,
            "volume": 100,
        }
    ])
    service = BacktestService(kline_repository=repository)
    bars = asyncio.run(
        service._load_bars(
            ["300308.SZ"],
            date(2026, 6, 1),
            date(2026, 6, 30),
            requirement_profile="OHLCV_RETURN_V1",
            required_fields=list(
                ResearchDataRequirementProfile.get(
                    "OHLCV_RETURN_V1"
                ).required_fields
            ),
        )
    )
    repository.get_bars_for_profile.assert_awaited_once_with(
        ["300308.SZ"],
        period="1d",
        adjustment="raw",
        research_use_scope="return_backtest",
        requirement_profile="OHLCV_RETURN_V1",
        required_fields=list(
            ResearchDataRequirementProfile.get("OHLCV_RETURN_V1").required_fields
        ),
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
    )
    assert "300308" in bars


def test_legacy_screener_loader_fails_before_database_access() -> None:
    with pytest.raises(RuntimeError, match="permanently disabled"):
        asyncio.run(ScreenerEngine()._load_legacy_universe_disabled())


def test_certified_store_writer_preserves_contract_and_marks_review() -> None:
    row = KlineContract.normalize_sohu_row(
        "603986.SH",
        ["2026-06-01", "10", "11", "1", "10", "9", "12", "123", "45.6", "2.5%"],
    )
    fetched = type(
        "Fetched",
        (),
        {"provider": "sohu", "source": "sohu_daily_kline"},
    )()
    stored = CertifiedStoreWriter._store_row(row, fetched, "batch", 100.0)
    assert stored["stock_code"] == "603986.SH"
    assert stored["provider"] == "sohu"
    assert stored["batch_id"] == "batch"
    assert len(stored["raw_hash"]) == 64
    assert "corporate-action" in stored["review_reason"]
