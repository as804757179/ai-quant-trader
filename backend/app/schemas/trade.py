from pydantic import BaseModel, Field


class OrderCreateRequest(BaseModel):
    stock_code: str = Field(..., min_length=6, max_length=10)
    side: str = Field(..., pattern="^(BUY|SELL)$")
    order_type: str = Field(default="LIMIT", pattern="^(MARKET|LIMIT)$")
    quantity: int = Field(..., gt=0)
    limit_price: float | None = None
    signal_id: str | None = None
    mode: str = Field(default="simulation", pattern="^(simulation|paper|live)$")
    order_reason: str | None = Field(default=None, max_length=500)
    approval_id: str | None = Field(default=None, max_length=100)
    data_certification_status: str = Field(default="not_applicable")
    # 实盘二次确认：须等于环境变量 LIVE_CONFIRM_TOKEN
    live_confirm: str | None = Field(
        default=None, description="实盘确认令牌，mode=live 时必填"
    )


class OrderCancelRequest(BaseModel):
    order_id: str = Field(..., min_length=1)
    mode: str = Field(default="simulation", pattern="^(simulation|paper|live)$")
