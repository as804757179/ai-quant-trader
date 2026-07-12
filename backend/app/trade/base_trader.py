from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class OrderRequest:
    stock_code: str
    side: str
    order_type: str
    quantity: int
    limit_price: float | None = None
    signal_id: str | None = None
    strategy_id: int | None = None
    trigger_source: str = "manual_order"
    operator: str | None = None
    order_reason: str | None = None
    caller: str | None = None
    approval_id: str | None = None
    approval_status: str = "pending"
    risk_check_id: str | None = None
    data_certification_status: str = "not_applicable"
    created_from_task: bool = False


@dataclass
class OrderResult:
    order_id: str
    status: str
    broker_order_id: str | None = None
    message: str = ""


@dataclass
class FillResult:
    order_id: str
    status: str
    filled_quantity: int = 0
    avg_fill_price: float = 0.0
    commission: float = 0.0
    stamp_tax: float = 0.0
    filled_at: datetime | None = None


@dataclass
class Position:
    stock_code: str
    total_qty: int
    available_qty: int
    avg_cost: float
    current_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0


@dataclass
class AccountInfo:
    total_assets: float
    cash: float
    market_value: float
    frozen_cash: float = 0.0
    daily_pnl: float = 0.0
    total_pnl: float = 0.0


class BaseTrader(ABC):
    @abstractmethod
    async def submit_order(self, request: OrderRequest) -> OrderResult:
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        pass

    @abstractmethod
    async def get_order_status(self, order_id: str) -> FillResult:
        pass

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        pass

    @abstractmethod
    async def get_account_info(self) -> AccountInfo:
        pass

    @abstractmethod
    async def sync_positions(self) -> None:
        pass
