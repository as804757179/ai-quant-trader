import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader")
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")

from app.data.certification import DataCertificationService
from app.data.quality_validator import KlineQualityValidator
from app.trade.simulation_trader import SimulationTrader


def _row(**overrides):
    row = {
        "stock_code": "000001", "period": "1d", "time": "2026-01-02T15:00:00+08:00",
        "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1000, "amount": 10500.0,
    }
    row.update(overrides)
    return row


def test_quality_validator_rejects_invalid_rows_and_sources():
    validator = KlineQualityValidator()
    assert not validator.validate_rows([], provider="sina", source="sina").passed
    assert validator.validate_rows([_row()], provider="sina", source="sina").passed
    assert not validator.validate_rows([_row()], provider="unknown", source="unknown").passed
    assert not validator.validate_rows([_row()], provider="synthetic", source="synthetic", is_synthetic=True).passed
    assert not validator.validate_rows([_row(high=9.0)], provider="sina", source="sina").passed
    assert not validator.validate_rows([_row(volume=0)], provider="sina", source="sina").passed
    assert not validator.validate_rows([_row(amount=0)], provider="sina", source="sina").passed
    assert not validator.validate_rows([_row(), _row()], provider="sina", source="sina").passed
    assert not validator.validate_rows([_row(time="2026-01-02T23:00:00+08:00")], provider="sina", source="sina").passed
    assert not validator.validate_rows([_row(time="bad-time")], provider="sina", source="sina").passed


def test_normal_provider_can_be_validated_but_not_auto_certified():
    service = DataCertificationService()
    result = service.validate_batch([_row()], provider="eastmoney", source="eastmoney", is_synthetic=False)
    assert result.passed


def test_certification_gate_rejects_dataset_without_certified_rows():
    async def run():
        db = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = 0
        db.execute = AsyncMock(return_value=result)
        with pytest.raises(ValueError, match="无已认证历史数据"):
            await DataCertificationService().assert_certified_dataset(
                db, ["000001"], "2026-06-01", "2026-06-30"
            )
    asyncio.run(run())


def test_simulation_refuses_uncertified_kline_fallback():
    async def run():
        data = MagicMock()
        data.get_quote = AsyncMock(return_value=None)
        data.get_certified_kline = AsyncMock(return_value=[])
        trader = SimulationTrader(MagicMock(), data)
        assert await trader._resolve_market("000001") is None
        data.get_certified_kline.assert_awaited_once()
    asyncio.run(run())


def test_simulation_prefers_quote_before_kline_fallback():
    async def run():
        data = MagicMock()
        data.get_quote = AsyncMock(return_value={
            "price": 10.0, "prev_close": 9.9, "high": 10.1, "low": 9.8, "volume": 1000,
        })
        data.get_certified_kline = AsyncMock(return_value=[])
        trader = SimulationTrader(MagicMock(), data)
        assert (await trader._resolve_market("000001")) is not None
        data.get_certified_kline.assert_not_awaited()
    asyncio.run(run())
