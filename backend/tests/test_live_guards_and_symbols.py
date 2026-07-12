"""实盘安全闸、代码转换、撤单与状态探测。"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")
os.environ.setdefault("TRADE_MODE", "live")
os.environ.setdefault("LIVE_CONFIRM_TOKEN", "secret-live-token")
os.environ.setdefault("LIVE_MAX_ORDER_VALUE", "50000")

# settings 可能已缓存，测试内直接改 settings 对象
from app.core import config as config_mod
from app.trade.base_trader import OrderRequest
from app.trade.execution_gate import ExecutionDecision
from app.trade.order_manager import OrderManager
from app.trade.qmt.symbols import from_qmt_symbol, to_qmt_symbol
from app.trade.qmt.xtquant_adapter import XtQuantAdapter


def _allowed_gate() -> MagicMock:
    gate = MagicMock()
    gate.evaluate.return_value = ExecutionDecision(True)
    return gate


def test_symbol_conversion() -> None:
    assert to_qmt_symbol("000001") == "000001.SZ"
    assert to_qmt_symbol("600519") == "600519.SH"
    assert to_qmt_symbol("000001.SZ") == "000001.SZ"
    assert from_qmt_symbol("600519.SH") == "600519"


def test_live_requires_confirm_token() -> None:
    async def _run() -> None:
        config_mod.settings.TRADE_MODE = "live"
        config_mod.settings.LIVE_CONFIRM_TOKEN = "secret-live-token"
        config_mod.settings.LIVE_MAX_ORDER_VALUE = 50_000

        db = AsyncMock()
        empty = MagicMock()
        empty.mappings.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=empty)

        fuse = MagicMock()
        fuse.is_fused = AsyncMock(return_value=False)
        manager = OrderManager(db, MagicMock(), fuse, {}, _allowed_gate())

        req = OrderRequest(
            stock_code="000001",
            side="BUY",
            order_type="LIMIT",
            quantity=100,
            limit_price=10.0,
        )
        r1 = await manager.create_order(req, "live", live_confirm=None)
        assert r1["success"] is False
        assert r1.get("error_code") == "LIVE_CONFIRM_REQUIRED"

        r2 = await manager.create_order(req, "live", live_confirm="wrong")
        assert r2["success"] is False

    asyncio.run(_run())


def test_live_max_order_value() -> None:
    async def _run() -> None:
        config_mod.settings.TRADE_MODE = "live"
        config_mod.settings.LIVE_CONFIRM_TOKEN = "tok"
        config_mod.settings.LIVE_MAX_ORDER_VALUE = 1000.0

        manager = OrderManager(AsyncMock(), MagicMock(), MagicMock(), {}, _allowed_gate())
        req = OrderRequest(
            stock_code="000001",
            side="BUY",
            order_type="LIMIT",
            quantity=100,
            limit_price=50.0,  # 5000 > 1000
        )
        r = await manager.create_order(req, "live", live_confirm="tok")
        assert r["success"] is False
        assert r.get("error_code") == "LIVE_ORDER_VALUE_EXCEEDED"

    asyncio.run(_run())


def test_xtquant_status_mapping() -> None:
    assert XtQuantAdapter._map_order_status(54) == "FILLED"
    assert XtQuantAdapter._map_order_status(53) == "CANCELLED"
    assert XtQuantAdapter._map_order_status(51) == "PARTIAL"
    assert XtQuantAdapter._map_side(23) == "BUY"
    assert XtQuantAdapter._map_side(24) == "SELL"


def test_xt_probe_without_sdk() -> None:
    adapter = XtQuantAdapter(qmt_path="", account_id="")
    info = adapter.probe_status()
    assert info["adapter"] == "xtquant"
    assert info["sdk_installed"] is False


def test_cancel_order_mode_check() -> None:
    async def _run() -> None:
        db = AsyncMock()
        row = MagicMock()
        row.mappings.return_value.first.return_value = {
            "id": "oid-1",
            "status": "SUBMITTED",
            "mode": "paper",
        }
        db.execute = AsyncMock(return_value=row)

        trader = MagicMock()
        trader.cancel_order = AsyncMock(return_value=True)
        # paper 与 live 都注册，才能测到 mode 不匹配分支
        manager = OrderManager(
            db, MagicMock(), MagicMock(), {"paper": trader, "live": trader}
        )
        r = await manager.cancel_order("oid-1", "paper")
        assert r["success"] is True
        trader.cancel_order.assert_awaited_with("oid-1")

        r2 = await manager.cancel_order("oid-1", "live")
        assert r2["success"] is False
        assert "不匹配" in r2["message"]

    asyncio.run(_run())
