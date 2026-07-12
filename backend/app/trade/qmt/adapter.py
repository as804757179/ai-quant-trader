"""券商适配抽象接口（QMT/xtquant 与 Mock 共用）。"""

from __future__ import annotations

import asyncio
import inspect
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

OrderEventCallback = Callable[["BrokerOrder"], Any]


@dataclass
class BrokerPosition:
    stock_code: str
    total_qty: int
    available_qty: int
    avg_cost: float
    market_value: float = 0.0


@dataclass
class BrokerAccount:
    total_assets: float
    cash: float
    market_value: float
    frozen_cash: float = 0.0


@dataclass
class BrokerOrder:
    broker_order_id: str
    stock_code: str
    side: str
    quantity: int
    status: str
    filled_quantity: int = 0
    avg_fill_price: float = 0.0
    message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class QmtAdapter(ABC):
    """
    miniQMT / 模拟券商统一接口。

    真实实现：XtQuantAdapter（Windows + xtquant）
    开发/联调：MockQmtAdapter
    """

    name: str = "base"

    def __init__(self) -> None:
        self._order_callbacks: list[OrderEventCallback] = []
        self._event_loop: asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        """供跨线程回调把协程投递回主 loop。"""
        self._event_loop = loop

    def register_order_callback(self, callback: OrderEventCallback) -> None:
        """订单状态变更回调（同步或 async）。"""
        if callback not in self._order_callbacks:
            self._order_callbacks.append(callback)

    def unregister_order_callback(self, callback: OrderEventCallback) -> None:
        if callback in self._order_callbacks:
            self._order_callbacks.remove(callback)

    def emit_order_event(self, order: BrokerOrder) -> None:
        """推送订单事件；线程安全地调度 async 回调。"""
        for cb in list(self._order_callbacks):
            try:
                result = cb(order)
                if inspect.isawaitable(result):
                    self._schedule_awaitable(result)
            except Exception:
                # 回调失败不影响交易主路径
                pass

    def _schedule_awaitable(self, awaitable: Awaitable[Any]) -> None:
        try:
            loop = self._event_loop
            if loop is None:
                try:
                    loop = asyncio.get_running_loop()
                    self._event_loop = loop
                except RuntimeError:
                    loop = None
            if loop is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(awaitable, loop)
            else:
                # 无运行中 loop：尽量创建临时 loop 执行
                asyncio.run(awaitable)  # type: ignore[arg-type]
        except Exception:
            pass

    @abstractmethod
    async def connect(self) -> bool:
        """连接交易端，成功返回 True。"""

    @abstractmethod
    async def disconnect(self) -> None:
        ...

    @abstractmethod
    async def is_connected(self) -> bool:
        ...

    @abstractmethod
    async def get_account(self) -> BrokerAccount:
        ...

    @abstractmethod
    async def get_positions(self) -> list[BrokerPosition]:
        ...

    @abstractmethod
    async def submit_order(
        self,
        *,
        stock_code: str,
        side: str,
        quantity: int,
        order_type: str = "LIMIT",
        limit_price: float | None = None,
    ) -> BrokerOrder:
        ...

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> bool:
        ...

    @abstractmethod
    async def query_order(self, broker_order_id: str) -> BrokerOrder | None:
        ...
