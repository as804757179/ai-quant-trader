from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ScreenRequest(BaseModel):
    conditions: dict[str, Any] = Field(
        default_factory=dict,
        description="筛选条件：filters / sort_by / sort_order",
    )
    preset_id: str | None = Field(default=None, description="预设条件 ID（与 conditions 二选一）")
    limit: int = Field(default=50, ge=1, le=200)


class ThemeScreenRequest(BaseModel):
    theme: str = Field(..., min_length=1, max_length=100, description="主题词，如 AI芯片、新能源")
    limit: int = Field(default=50, ge=1, le=200)


class ScreenerStockItem(BaseModel):
    code: str
    name: str | None = None
    sector: str | None = None
    price: float | None = None
    change_pct: float | None = None
    volume: float | None = None
    turnover_rate: float | None = None
    volume_ratio: float | None = None
    market_cap: float | None = None
    ai_action: str | None = None
    ai_confidence: float | None = None


class ScreenResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    from_cache: bool = False
    conditions: dict[str, Any] | None = None
    preset_id: str | None = None
    preset_name: str | None = None
    theme: str | None = None