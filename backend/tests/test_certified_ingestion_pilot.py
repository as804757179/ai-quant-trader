import asyncio
import json
import os
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader"
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")

from app.data.certification import DataCertificationService
from app.data.sohu_daily_importer import (
    SohuDailyKlineImporter,
    ProviderFetchResult,
)
from app.data.quality_validator import KlineQualityValidator, QualityResult
from app.backtest.service import BacktestService
from app.screener.engine import ScreenerEngine


RAW_ROWS = [
    ["2026-06-01", "10.00", "10.50", "0.50", "5.00%", "9.90", "10.80", "1000", "102.00", "1.20%", "10.00"],
    ["2026-06-02", "10.50", "10.60", "0.10", "0.95%", "10.30", "10.90", "1200", "127.00", "1.30%", "10.00"],
]


def _rows():
    return SohuDailyKlineImporter.normalize_rows(
        "300308", RAW_ROWS, date(2026, 6, 1), date(2026, 6, 30)
    )


def _fetch_result(rows=None):
    return ProviderFetchResult(
        stock_code="300308",
        provider="sohu",
        source="sohu_daily_kline",
        provider_priority=1,
        fallback_used=False,
        fetch_url_or_endpoint="https://q.stock.sohu.com/hisHq",
        fetch_time=datetime(2026, 7, 11, tzinfo=timezone.utc),
        raw_hash="a" * 64,
        rows=rows or _rows(),
    )


def test_provider_fetch_returns_explicit_metadata_without_fallback() -> None:
    async def _run() -> None:
        payload = [{"status": 0, "code": "cn_300308", "hq": RAW_ROWS}]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=json.dumps(payload).encode(), request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        importer = SohuDailyKlineImporter(client=client)
        try:
            result = await importer.fetch("300308.SZ", date(2026, 6, 1), date(2026, 6, 30))
        finally:
            await client.aclose()
        assert result.provider == "sohu"
        assert result.source == "sohu_daily_kline"
        assert result.provider_priority == 1
        assert result.fallback_used is False
        assert len(result.raw_hash) == 64

    asyncio.run(_run())


def test_daily_normalize_uses_1500_asia_shanghai_and_no_duplicates() -> None:
    rows = _rows()
    assert {row["time"].hour for row in rows} == {15}
    assert {row["time"].utcoffset().total_seconds() for row in rows} == {8 * 3600}
    assert len({row["time"].date() for row in rows}) == len(rows)


def test_unknown_fallback_and_synthetic_cannot_pass_validation() -> None:
    validator = KlineQualityValidator()
    rows = _rows()
    assert validator.validate_rows(
        rows, provider="sohu", source="sohu_daily_kline"
    ).passed
    assert not validator.validate_rows(rows, provider="unknown", source="unknown").passed
    assert not validator.validate_rows(rows, provider="sohu", source="unknown").passed
    assert not validator.validate_rows(
        rows, provider="synthetic", source="synthetic", is_synthetic=True
    ).passed


def test_empty_duplicate_2300_and_invalid_prices_are_rejected() -> None:
    validator = KlineQualityValidator()
    assert not validator.validate_rows(
        [], provider="sohu", source="sohu_daily_kline"
    ).passed
    rows = _rows()
    assert not validator.validate_rows(
        [rows[0], rows[0]], provider="sohu", source="sohu_daily_kline"
    ).passed
    bad_time = [{**rows[0], "time": rows[0]["time"].replace(hour=23)}]
    assert not validator.validate_rows(
        bad_time, provider="sohu", source="sohu_daily_kline"
    ).passed
    for override in ({"amount": 0}, {"volume": 0}, {"high": 9.0}):
        assert not validator.validate_rows(
            [{**rows[0], **override}],
            provider="sohu",
            source="sohu_daily_kline",
        ).passed


def test_create_batch_records_provider_metadata_and_row_counts() -> None:
    async def _run() -> None:
        db = AsyncMock()
        service = DataCertificationService()
        batch_id, quality = await service.create_batch(
            db,
            _rows(),
            provider="sohu",
            source="sohu_daily_kline",
            period="1d",
            provider_priority=1,
            fallback_used=False,
            fetch_endpoint="https://example.test/kline",
            raw_hash="b" * 64,
        )
        assert batch_id
        assert quality.passed
        params = db.execute.await_args.args[1]
        assert params["accepted"] == 2
        assert params["rejected"] == 0
        assert params["provider_priority"] == 1
        assert params["fallback_used"] is False

    asyncio.run(_run())


def test_successful_ingest_writes_provenance_and_certifies_batch() -> None:
    async def _run() -> None:
        certification = MagicMock()
        certification.create_batch = AsyncMock(
            return_value=("batch-1", QualityResult(True, 100.0, []))
        )
        certification.record_provenance = AsyncMock()
        certification.certify_kline_batch = AsyncMock()
        db = AsyncMock()
        collision = MagicMock()
        collision.scalar.return_value = 0
        db.execute = AsyncMock(side_effect=[collision, MagicMock()])
        importer = SohuDailyKlineImporter(
            client=MagicMock(), certification=certification
        )
        result = await importer.ingest(db, _fetch_result())
        assert result.status == "certified"
        assert result.accepted_rows == 2
        assert result.rejected_rows == 0
        provenance_kwargs = certification.record_provenance.await_args.kwargs
        assert provenance_kwargs["batch_id"] == "batch-1"
        assert provenance_kwargs["provider"] == "sohu"
        assert provenance_kwargs["source"] == "sohu_daily_kline"
        assert provenance_kwargs["is_synthetic"] is False
        certification.certify_kline_batch.assert_awaited_once_with(db, "batch-1")

    asyncio.run(_run())


def test_existing_natural_day_collision_rejects_without_overwrite() -> None:
    async def _run() -> None:
        certification = MagicMock()
        certification.create_batch = AsyncMock(
            return_value=("batch-collision", QualityResult(True, 100.0, []))
        )
        certification.record_provenance = AsyncMock()
        certification.certify_kline_batch = AsyncMock()
        db = AsyncMock()
        collision = MagicMock()
        collision.scalar.return_value = 2
        db.execute = AsyncMock(side_effect=[collision, MagicMock()])
        importer = SohuDailyKlineImporter(
            client=MagicMock(), certification=certification
        )
        result = await importer.ingest(db, _fetch_result())
        assert result.status == "rejected"
        assert result.accepted_rows == 0
        assert result.rejected_rows == 2
        assert "legacy data preserved" in result.reject_reason
        certification.record_provenance.assert_not_awaited()
        certification.certify_kline_batch.assert_not_awaited()

    asyncio.run(_run())


def test_backtest_execution_remains_release_locked() -> None:
    async def _run() -> None:
        with pytest.raises(ValueError, match="真实回测执行仍关闭"):
            await BacktestService().create_and_run(
                strategy_type="dual_ma",
                stock_codes=["300308"],
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 30),
            )

    asyncio.run(_run())


def test_screener_candidate_output_remains_release_locked() -> None:
    result = asyncio.run(ScreenerEngine(release_enabled=False).screen({}, limit=10))
    assert result["items"] == []
    assert result["release_status"] == "blocked"
    assert result["blocked_reason"] == "CERTIFIED_SCREENER_OUTPUT_DISABLED"
