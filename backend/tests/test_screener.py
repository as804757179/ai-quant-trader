import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")
os.environ.setdefault("WS_REDIS_ENABLED", "false")

from app.main import app
from app.screener.engine import ScreenerEngine
from app.screener.factors import FactorLibrary


SAMPLE_UNIVERSE: list[dict[str, Any]] = [
    {
        "code": "000001",
        "name": "平安银行",
        "sector": "银行",
        "change_pct": 1.2,
        "volume_ratio": 0.9,
        "turnover_rate": 0.5,
        "market_cap": 2e11,
        "ai_action": "HOLD",
        "ai_confidence": 0.5,
        "pb_ratio": 0.8,
        "recent_return_5d": -1.0,
        "main_net_in_5d": -100,
        "amount": 5e8,
        "roe": 10.0,
    },
    {
        "code": "300750",
        "name": "宁德时代",
        "sector": "电力设备",
        "change_pct": 4.5,
        "volume_ratio": 1.8,
        "turnover_rate": 2.1,
        "market_cap": 8e11,
        "ai_action": "BUY",
        "ai_confidence": 0.72,
        "pb_ratio": 3.5,
        "recent_return_5d": 6.0,
        "main_net_in_5d": 5000,
        "amount": 3e9,
        "roe": 18.0,
    },
    {
        "code": "688981",
        "name": "中芯国际",
        "sector": "电子",
        "change_pct": 3.2,
        "volume_ratio": 1.5,
        "turnover_rate": 1.8,
        "market_cap": 4e11,
        "ai_action": "BUY",
        "ai_confidence": 0.68,
        "pb_ratio": 2.0,
        "recent_return_5d": -4.0,
        "main_net_in_5d": 2000,
        "amount": 2e9,
        "roe": 9.0,
    },
    {
        "code": "601012",
        "name": "隆基绿能",
        "sector": "电力设备",
        "change_pct": -2.0,
        "volume_ratio": 0.8,
        "turnover_rate": 1.0,
        "market_cap": 1.5e11,
        "ai_action": "HOLD",
        "ai_confidence": 0.4,
        "pb_ratio": 1.8,
        "recent_return_5d": -6.0,
        "main_net_in_5d": 800,
        "amount": 8e8,
        "roe": 12.0,
    },
]


def test_factor_library_basic_filters() -> None:
    lib = FactorLibrary()
    stock = SAMPLE_UNIVERSE[1]

    assert lib.apply_condition(stock, {"field": "change_pct", "op": "gte", "value": 3}) is True
    assert lib.apply_condition(stock, {"field": "volume_ratio", "op": "gte", "value": 1.5}) is True
    assert lib.sector_match("电力设备", ["电力设备", "汽车"]) is True
    assert lib.volume_ratio(1800, 1000) == 1.8
    assert lib.change_pct(10.5, 10.0) == 5.0


def test_screen_custom_conditions() -> None:
    async def _run() -> None:
        engine = ScreenerEngine(cache=AsyncMock())
        engine.cache.get = AsyncMock(return_value=None)
        engine.cache.set = AsyncMock()

        with patch.object(engine, "_load_universe", AsyncMock(return_value=SAMPLE_UNIVERSE)):
            result = await engine.screen(
                {
                    "filters": [
                        {"field": "change_pct", "op": "gte", "value": 3},
                        {"field": "volume_ratio", "op": "gte", "value": 1.2},
                    ],
                    "sort_by": "change_pct",
                    "sort_order": "desc",
                },
                limit=10,
            )

        assert result["total"] == 2
        codes = [item["code"] for item in result["items"]]
        assert codes[0] == "300750"
        assert "688981" in codes

    asyncio.run(_run())


def test_screen_preset_ai_momentum() -> None:
    async def _run() -> None:
        engine = ScreenerEngine(cache=AsyncMock())
        engine.cache.get = AsyncMock(return_value=None)
        engine.cache.set = AsyncMock()

        with patch.object(engine, "_load_universe", AsyncMock(return_value=SAMPLE_UNIVERSE)):
            result = await engine.screen_preset("ai_momentum", limit=10)

        assert result["preset_id"] == "ai_momentum"
        assert result["preset_name"] == "AI动量"
        assert result["total"] >= 1
        assert all(item["change_pct"] >= 2 for item in result["items"])

    asyncio.run(_run())


def test_screen_preset_value_rebound() -> None:
    async def _run() -> None:
        engine = ScreenerEngine(cache=AsyncMock())
        engine.cache.get = AsyncMock(return_value=None)
        engine.cache.set = AsyncMock()

        with patch.object(engine, "_load_universe", AsyncMock(return_value=SAMPLE_UNIVERSE)):
            result = await engine.screen_preset("value_rebound", limit=10)

        assert result["preset_id"] == "value_rebound"
        codes = [item["code"] for item in result["items"]]
        assert "601012" in codes

    asyncio.run(_run())


def test_screen_by_theme_new_energy() -> None:
    async def _run() -> None:
        engine = ScreenerEngine(cache=AsyncMock())
        engine.cache.get = AsyncMock(return_value=None)
        engine.cache.set = AsyncMock()

        with (
            patch.object(engine, "_load_universe", AsyncMock(return_value=SAMPLE_UNIVERSE)),
            patch.object(engine, "_find_theme_stock_codes", AsyncMock(return_value=set())),
        ):
            result = await engine.screen_by_theme("新能源", limit=10)

        assert result["theme"] == "新能源"
        codes = {item["code"] for item in result["items"]}
        assert "300750" in codes
        assert "601012" in codes

    asyncio.run(_run())


def test_screen_preset_sector_leader() -> None:
    async def _run() -> None:
        engine = ScreenerEngine(cache=AsyncMock())
        engine.cache.get = AsyncMock(return_value=None)
        engine.cache.set = AsyncMock()

        with patch.object(engine, "_load_universe", AsyncMock(return_value=SAMPLE_UNIVERSE)):
            result = await engine.screen_preset("sector_leader", limit=10)

        assert result["preset_id"] == "sector_leader"
        for item in result["items"]:
            assert item.get("roe", 0) >= 8

    asyncio.run(_run())


def test_screen_by_theme_ai_chip() -> None:
    async def _run() -> None:
        engine = ScreenerEngine(cache=AsyncMock())
        engine.cache.get = AsyncMock(return_value=None)
        engine.cache.set = AsyncMock()

        with (
            patch.object(engine, "_load_universe", AsyncMock(return_value=SAMPLE_UNIVERSE)),
            patch.object(engine, "_find_theme_stock_codes", AsyncMock(return_value={"688981"})),
        ):
            result = await engine.screen_by_theme("AI芯片", limit=10)

        codes = {item["code"] for item in result["items"]}
        assert "688981" in codes

    asyncio.run(_run())


async def _post(path: str, json_body: dict) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=json_body)


async def _get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def test_api_presets_endpoint() -> None:
    response = asyncio.run(_get("/api/v1/screener/presets"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    ids = {item["id"] for item in payload["data"]["items"]}
    assert ids == {"ai_momentum", "value_rebound", "sector_leader"}


def test_api_screen_endpoint() -> None:
    mock_result = {
        "items": SAMPLE_UNIVERSE[:1],
        "total": 1,
        "limit": 10,
        "from_cache": False,
        "conditions": {},
    }

    with patch("app.api.screener.ScreenerEngine.screen", AsyncMock(return_value=mock_result)):
        response = asyncio.run(
            _post(
                "/api/v1/screener/screen",
                {
                    "conditions": {
                        "filters": [{"field": "change_pct", "op": "gte", "value": 1}],
                    },
                    "limit": 10,
                },
            )
        )

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1


def test_api_theme_endpoint() -> None:
    mock_result = {
        "items": [SAMPLE_UNIVERSE[1]],
        "total": 1,
        "limit": 10,
        "theme": "新能源",
        "from_cache": False,
    }

    with patch(
        "app.api.screener.ScreenerEngine.screen_by_theme",
        AsyncMock(return_value=mock_result),
    ):
        response = asyncio.run(
            _post("/api/v1/screener/theme", {"theme": "新能源", "limit": 10})
        )

    assert response.status_code == 200
    assert response.json()["data"]["theme"] == "新能源"