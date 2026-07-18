from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OrderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stock_code: str = Field(..., min_length=6, max_length=10)
    side: str = Field(..., pattern="^(BUY|SELL)$")
    order_type: str = Field(default="LIMIT", pattern="^(MARKET|LIMIT)$")
    quantity: int = Field(..., gt=0)
    limit_price: float | None = None
    signal_id: str | None = None
    mode: str = Field(default="simulation", pattern="^(simulation|paper|live)$")
    order_reason: str | None = Field(default=None, max_length=500)
    execution_authorization_id: str | None = Field(default=None, max_length=100)
    client_intent_key: str = Field(..., min_length=8, max_length=128)
    # 实盘二次确认：须等于环境变量 LIVE_CONFIRM_TOKEN
    live_confirm: str | None = Field(
        default=None, description="实盘确认令牌，mode=live 时必填"
    )


class OrderCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: UUID
    mode: str = Field(default="simulation", pattern="^(simulation|paper|live)$")
    execution_authorization_id: str = Field(..., min_length=1, max_length=100)


class PreTradeCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stock_code: str = Field(..., min_length=6, max_length=10)
    side: str = Field(..., pattern="^(BUY|SELL)$")
    order_type: str = Field(default="LIMIT", pattern="^(MARKET|LIMIT)$")
    quantity: int = Field(..., gt=0)
    limit_price: float | None = None
    signal_id: str | None = None
    mode: str = Field(default="simulation", pattern="^(simulation|paper|live)$")


class ExecutionApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stock_code: str = Field(..., min_length=6, max_length=10)
    side: str = Field(..., pattern="^(BUY|SELL)$")
    order_type: str = Field(default="LIMIT", pattern="^(MARKET|LIMIT)$")
    quantity: int = Field(..., gt=0)
    limit_price: float | None = None
    signal_id: str | None = None
    mode: str = Field(default="simulation", pattern="^(simulation|paper|live)$")
    order_reason: str | None = Field(default=None, max_length=500)
    data_authorization_ref: str = Field(
        ..., min_length=1, max_length=200,
        description="服务端 EXECUTION_REFERENCE_V1 审核记录标识",
    )
    expires_in_seconds: int = Field(default=900, ge=300, le=3600)


class OperationApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: Literal[
        "trade.order.cancel",
        "risk.fuse.recover",
        "trade.simulation.release_t1",
        "trade.reconcile",
    ]
    payload: dict[str, Any]
    expires_in_seconds: int = Field(default=900, ge=300, le=3600)
