from pydantic import BaseModel, Field


class OrderCreateRequest(BaseModel):
    stock_code: str = Field(..., min_length=6, max_length=10)
    side: str = Field(..., pattern="^(BUY|SELL)$")
    order_type: str = Field(default="LIMIT", pattern="^(MARKET|LIMIT)$")
    quantity: int = Field(..., gt=0)
    limit_price: float | None = None
    signal_id: str | None = None
    mode: str = Field(default="simulation", pattern="^(simulation|paper|live)$")