"""真实 xtquant 适配（Windows + miniQMT；无 SDK 时不可用）。"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog

from app.trade.qmt.adapter import (
    BrokerAccount,
    BrokerOrder,
    BrokerPosition,
    QmtAdapter,
)
from app.trade.qmt.symbols import from_qmt_symbol, to_qmt_symbol

logger = structlog.get_logger(__name__)


class QmtNotAvailableError(RuntimeError):
    """xtquant / miniQMT 不可用。"""


def _run_sync(fn, *args, **kwargs):
    """在线程中执行同步 SDK 调用。"""
    return asyncio.to_thread(fn, *args, **kwargs)


class XtQuantAdapter(QmtAdapter):
    """
    生产环境需：
    1. Windows + 已登录 miniQMT
    2. 券商提供的 xtquant 包
    3. QMT_PATH / QMT_ACCOUNT_ID
    """

    name = "xtquant"

    def __init__(
        self,
        *,
        qmt_path: str | None = None,
        account_id: str | None = None,
        account_type: str | None = None,
        session_id: int | None = None,
    ) -> None:
        super().__init__()
        self.qmt_path = qmt_path or os.getenv("QMT_PATH", "")
        self.account_id = account_id or os.getenv("QMT_ACCOUNT_ID", "")
        self.account_type = account_type or os.getenv("QMT_ACCOUNT_TYPE", "STOCK")
        self.session_id = session_id or int(os.getenv("QMT_SESSION_ID", "123456"))
        self._connected = False
        self._trader: Any = None
        self._account: Any = None
        self._mods: dict[str, Any] | None = None
        self._callback_obj: Any = None

    def _import_xt(self) -> dict[str, Any]:
        if self._mods is not None:
            return self._mods
        try:
            from xtquant import xtconstant  # type: ignore
            from xtquant import xttrader  # type: ignore
            from xtquant.xttype import StockAccount  # type: ignore
        except ImportError as exc:
            raise QmtNotAvailableError(
                "未安装 xtquant，无法连接真实 QMT。开发请使用 MockQmtAdapter。"
            ) from exc
        self._mods = {
            "xttrader": xttrader,
            "xtconstant": xtconstant,
            "StockAccount": StockAccount,
        }
        return self._mods

    async def connect(self) -> bool:
        mods = self._import_xt()
        if not self.qmt_path or not self.account_id:
            raise QmtNotAvailableError("请配置 QMT_PATH 与 QMT_ACCOUNT_ID")

        adapter_self = self

        def _connect() -> tuple[Any, Any, int, Any]:
            trader = mods["xttrader"].XtQuantTrader(self.qmt_path, self.session_id)
            callback = adapter_self._build_trader_callback(mods)
            if callback is not None:
                try:
                    trader.register_callback(callback)
                except Exception as reg_exc:
                    logger.warning("qmt_register_callback_failed", error=str(reg_exc))
            trader.start()
            try:
                acc = mods["StockAccount"](self.account_id, self.account_type)
            except TypeError:
                acc = mods["StockAccount"](self.account_id)
            code = trader.connect()
            if code == 0:
                trader.subscribe(acc)
            return trader, acc, code, callback

        try:
            trader, acc, code, callback = await _run_sync(_connect)
            if code != 0:
                logger.error("qmt_connect_failed", code=code)
                return False
            self._trader = trader
            self._account = acc
            self._callback_obj = callback
            self._connected = True
            logger.info(
                "qmt_connected",
                account_id=self.account_id,
                callback=callback is not None,
            )
            return True
        except QmtNotAvailableError:
            raise
        except Exception as exc:
            logger.error("qmt_connect_error", error=str(exc), exc_info=True)
            raise QmtNotAvailableError(str(exc)) from exc

    def _build_trader_callback(self, mods: dict[str, Any]) -> Any:
        """注册 XtQuantTraderCallback，把 on_stock_order/on_stock_trade 转到 emit_order_event。"""
        try:
            base = getattr(mods["xttrader"], "XtQuantTraderCallback", None)
            if base is None:
                return None
        except Exception:
            return None

        adapter = self

        class _BridgeCallback(base):  # type: ignore[misc,valid-type]
            def on_disconnected(self):  # noqa: N802
                logger.warning("qmt_callback_disconnected")

            def on_stock_order(self, order):  # noqa: N802
                try:
                    bo = adapter._order_from_xt(order)
                    if bo:
                        adapter.emit_order_event(bo)
                except Exception as exc:
                    logger.warning("qmt_on_stock_order_error", error=str(exc))

            def on_stock_trade(self, trade):  # noqa: N802
                try:
                    bo = adapter._trade_from_xt(trade)
                    if bo:
                        adapter.emit_order_event(bo)
                except Exception as exc:
                    logger.warning("qmt_on_stock_trade_error", error=str(exc))

            def on_order_error(self, order_error):  # noqa: N802
                try:
                    oid = str(
                        getattr(order_error, "order_id", "")
                        or getattr(order_error, "order_sysid", "")
                        or ""
                    )
                    msg = str(
                        getattr(order_error, "error_msg", None)
                        or getattr(order_error, "error_msg", "")
                        or order_error
                    )
                    bo = BrokerOrder(
                        broker_order_id=oid,
                        stock_code="",
                        side="BUY",
                        quantity=0,
                        status="FAILED",
                        message=msg,
                    )
                    adapter.emit_order_event(bo)
                except Exception as exc:
                    logger.warning("qmt_on_order_error", error=str(exc))

        return _BridgeCallback()

    def _order_from_xt(self, order: Any) -> BrokerOrder | None:
        oid = str(
            getattr(order, "order_id", None)
            or getattr(order, "order_sysid", None)
            or ""
        )
        if not oid:
            return None
        symbol = str(getattr(order, "stock_code", "") or "")
        status_raw = getattr(order, "order_status", None)
        return BrokerOrder(
            broker_order_id=oid,
            stock_code=from_qmt_symbol(symbol),
            side=self._map_side(getattr(order, "order_type", None)),
            quantity=int(getattr(order, "order_volume", 0) or 0),
            status=self._map_order_status(status_raw),
            filled_quantity=int(getattr(order, "traded_volume", 0) or 0),
            avg_fill_price=float(getattr(order, "traded_price", 0) or 0),
            message=str(getattr(order, "status_msg", "") or ""),
            raw={"source": "on_stock_order", "order_status": status_raw},
        )

    def _trade_from_xt(self, trade: Any) -> BrokerOrder | None:
        oid = str(
            getattr(trade, "order_id", None)
            or getattr(trade, "order_sysid", None)
            or ""
        )
        if not oid:
            return None
        symbol = str(getattr(trade, "stock_code", "") or "")
        vol = int(getattr(trade, "traded_volume", 0) or getattr(trade, "volume", 0) or 0)
        price = float(getattr(trade, "traded_price", 0) or getattr(trade, "price", 0) or 0)
        return BrokerOrder(
            broker_order_id=oid,
            stock_code=from_qmt_symbol(symbol),
            side=self._map_side(getattr(trade, "order_type", None)),
            quantity=vol,
            status="FILLED" if vol > 0 else "PARTIAL",
            filled_quantity=vol,
            avg_fill_price=price,
            message="on_stock_trade",
            raw={"source": "on_stock_trade"},
        )

    async def disconnect(self) -> None:
        trader = self._trader
        self._connected = False
        self._trader = None
        self._account = None
        if trader is not None:
            try:
                stop = getattr(trader, "stop", None)
                if callable(stop):
                    await _run_sync(stop)
            except Exception as exc:
                logger.warning("qmt_disconnect_error", error=str(exc))

    async def is_connected(self) -> bool:
        return self._connected and self._trader is not None

    async def get_account(self) -> BrokerAccount:
        self._ensure()

        def _query() -> Any:
            return self._trader.query_stock_asset(self._account)

        asset = await _run_sync(_query)
        if asset is None:
            return BrokerAccount(total_assets=0, cash=0, market_value=0)
        cash = float(getattr(asset, "cash", 0) or 0)
        total = float(
            getattr(asset, "total_asset", None)
            or getattr(asset, "total_assets", None)
            or 0
        )
        mv = float(getattr(asset, "market_value", 0) or 0)
        frozen = float(getattr(asset, "frozen_cash", 0) or 0)
        if total <= 0:
            total = cash + mv
        return BrokerAccount(
            total_assets=total,
            cash=cash,
            market_value=mv,
            frozen_cash=frozen,
        )

    async def get_positions(self) -> list[BrokerPosition]:
        self._ensure()

        def _query() -> list:
            rows = self._trader.query_stock_positions(self._account)
            return list(rows or [])

        rows = await _run_sync(_query)
        out: list[BrokerPosition] = []
        for p in rows:
            symbol = getattr(p, "stock_code", "") or getattr(p, "instrument_id", "")
            code = from_qmt_symbol(str(symbol))
            total = int(getattr(p, "volume", 0) or getattr(p, "total_qty", 0) or 0)
            avail = int(
                getattr(p, "can_use_volume", None)
                or getattr(p, "available_qty", None)
                or total
            )
            cost = float(
                getattr(p, "avg_price", None)
                or getattr(p, "open_price", None)
                or 0
            )
            mv = float(getattr(p, "market_value", 0) or cost * total)
            if total <= 0:
                continue
            out.append(
                BrokerPosition(
                    stock_code=code,
                    total_qty=total,
                    available_qty=avail,
                    avg_cost=cost,
                    market_value=mv,
                )
            )
        return out

    async def submit_order(
        self,
        *,
        stock_code: str,
        side: str,
        quantity: int,
        order_type: str = "LIMIT",
        limit_price: float | None = None,
    ) -> BrokerOrder:
        self._ensure()
        mods = self._import_xt()
        xtc = mods["xtconstant"]
        symbol = to_qmt_symbol(stock_code)
        side_u = side.upper()
        buy = getattr(xtc, "STOCK_BUY", 23)
        sell = getattr(xtc, "STOCK_SELL", 24)
        order_side = buy if side_u == "BUY" else sell

        if order_type.upper() == "MARKET":
            price_type = getattr(xtc, "LATEST_PRICE", getattr(xtc, "MARKET_PRICE", 5))
            price = float(limit_price or 0)
        else:
            price_type = getattr(xtc, "FIX_PRICE", 11)
            if limit_price is None or limit_price <= 0:
                return BrokerOrder(
                    broker_order_id="",
                    stock_code=stock_code,
                    side=side_u,
                    quantity=quantity,
                    status="FAILED",
                    message="限价单需要有效 limit_price",
                )
            price = float(limit_price)

        def _order() -> int:
            return self._trader.order_stock(
                self._account,
                symbol,
                order_side,
                int(quantity),
                price_type,
                price,
                "ai_quant",
                "live_order",
            )

        try:
            seq = await _run_sync(_order)
        except Exception as exc:
            logger.error("qmt_order_error", error=str(exc), stock=symbol)
            return BrokerOrder(
                broker_order_id="",
                stock_code=stock_code,
                side=side_u,
                quantity=quantity,
                status="FAILED",
                message=f"下单异常: {exc}",
            )

        if seq is None or (isinstance(seq, int) and seq < 0):
            return BrokerOrder(
                broker_order_id=str(seq or ""),
                stock_code=stock_code,
                side=side_u,
                quantity=quantity,
                status="FAILED",
                message=f"QMT 拒单 seq={seq}",
            )

        # 提交成功后异步查询一次状态（可能仍为未成交）
        broker_id = str(seq)
        status = "SUBMITTED"
        filled_qty = 0
        avg_price = 0.0
        try:
            await asyncio.sleep(0.3)
            q = await self.query_order(broker_id)
            if q:
                status = q.status
                filled_qty = q.filled_quantity
                avg_price = q.avg_fill_price
        except Exception:
            pass

        return BrokerOrder(
            broker_order_id=broker_id,
            stock_code=stock_code,
            side=side_u,
            quantity=quantity,
            status=status,
            filled_quantity=filled_qty,
            avg_fill_price=avg_price,
            message=f"QMT 已提交 seq={broker_id}",
        )

    async def cancel_order(self, broker_order_id: str) -> bool:
        self._ensure()

        def _cancel() -> int:
            # 优先按 order_id 撤单
            fn = getattr(self._trader, "cancel_order_stock", None)
            if callable(fn):
                try:
                    return int(fn(self._account, int(broker_order_id)))
                except (TypeError, ValueError):
                    return int(fn(self._account, broker_order_id))
            fn2 = getattr(self._trader, "cancel_order_stock_async", None)
            if callable(fn2):
                return int(fn2(self._account, int(broker_order_id)))
            raise QmtNotAvailableError("SDK 无撤单接口")

        try:
            code = await _run_sync(_cancel)
            ok = code == 0
            logger.info("qmt_cancel", broker_order_id=broker_order_id, code=code)
            return ok
        except Exception as exc:
            logger.error("qmt_cancel_error", error=str(exc))
            return False

    async def query_order(self, broker_order_id: str) -> BrokerOrder | None:
        self._ensure()

        def _query() -> list:
            rows = self._trader.query_stock_orders(self._account)
            return list(rows or [])

        rows = await _run_sync(_query)
        target = str(broker_order_id)
        for o in rows:
            oid = str(
                getattr(o, "order_id", None)
                or getattr(o, "order_sysid", None)
                or getattr(o, "strategy_name", "")
                or ""
            )
            seq = str(getattr(o, "order_remark", "") or getattr(o, "seq", "") or "")
            if target not in (oid, seq) and target not in oid:
                # 也匹配数字 order_id
                if str(getattr(o, "order_id", "")) != target:
                    continue
            status_raw = getattr(o, "order_status", None) or getattr(o, "status", "")
            status = self._map_order_status(status_raw)
            symbol = str(getattr(o, "stock_code", "") or "")
            return BrokerOrder(
                broker_order_id=target,
                stock_code=from_qmt_symbol(symbol),
                side=self._map_side(getattr(o, "order_type", None)),
                quantity=int(getattr(o, "order_volume", 0) or 0),
                status=status,
                filled_quantity=int(getattr(o, "traded_volume", 0) or 0),
                avg_fill_price=float(getattr(o, "traded_price", 0) or 0),
                message=str(getattr(o, "status_msg", "") or ""),
                raw={"order_status": status_raw},
            )
        return None

    @staticmethod
    def _map_side(order_type: Any) -> str:
        try:
            v = int(order_type)
            # xtconstant STOCK_BUY 常见 23
            if v in (23, 1):
                return "BUY"
            if v in (24, 2):
                return "SELL"
        except (TypeError, ValueError):
            pass
        s = str(order_type or "").upper()
        if "SELL" in s or "卖" in s:
            return "SELL"
        return "BUY"

    @staticmethod
    def _map_order_status(raw: Any) -> str:
        """映射 QMT 状态到内部状态机。"""
        try:
            code = int(raw)
        except (TypeError, ValueError):
            s = str(raw or "").upper()
            if "FILL" in s or "成" in s:
                return "FILLED"
            if "CANCEL" in s or "撤" in s:
                return "CANCELLED"
            if "REJECT" in s or "废" in s:
                return "FAILED"
            if "PART" in s:
                return "PARTIAL"
            return "SUBMITTED"

        # 常见 xtconstant 订单状态（不同版本可能略有差异）
        mapping = {
            48: "SUBMITTED",  # 未报
            49: "SUBMITTED",  # 待报
            50: "SUBMITTED",  # 已报
            51: "PARTIAL",  # 部成
            52: "PARTIAL",  # 部成待撤
            53: "CANCELLED",
            54: "FILLED",
            55: "FAILED",
            56: "FAILED",
        }
        return mapping.get(code, "SUBMITTED")

    def _ensure(self) -> None:
        if not self._connected or self._trader is None:
            raise QmtNotAvailableError("QMT 未连接，请先 connect()")

    def probe_status(self) -> dict[str, Any]:
        """不连接，仅探测环境是否具备真实 QMT 条件。"""
        info: dict[str, Any] = {
            "adapter": self.name,
            "qmt_path_set": bool(self.qmt_path),
            "account_id_set": bool(self.account_id),
            "sdk_installed": False,
            "connected": self._connected,
        }
        try:
            self._import_xt()
            info["sdk_installed"] = True
        except QmtNotAvailableError as exc:
            info["error"] = str(exc)
        return info
