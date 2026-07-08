from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    force_refresh: bool = Field(default=False, description="强制重新分析（忽略缓存）")
    strategy_id: int | None = Field(default=None, description="关联策略 ID")


class AgentResultSummary(BaseModel):
    agent_name: str
    model: str
    status: str
    latency_ms: int
    output: dict[str, Any]
    degraded: bool = False
    error_msg: str | None = None


class SignalPayload(BaseModel):
    id: str | None = None
    action: str
    confidence: float
    raw_confidence: float | None = None
    risk_level: str
    price_at: float | None = None
    reason: str
    scores: dict[str, float] = Field(default_factory=dict)
    degraded_agents: list[str] = Field(default_factory=list)
    signal_time: str | None = None
    valid_until: str | None = None


class AnalyzeResponseData(BaseModel):
    code: str
    signal: SignalPayload
    scores: dict[str, float]
    reason: str
    agent_results: dict[str, AgentResultSummary]
    agent_statuses: dict[str, str] = Field(default_factory=dict)
    latency_ms: int
    from_cache: bool = False
    signal_id: str | None = None
    data_quality_score: float | None = None


class SignalListItem(BaseModel):
    id: str
    stock_code: str
    action: str
    confidence: float
    risk_level: str
    price_at: float | None = None
    reason: str
    signal_time: str | None = None
    valid_until: str | None = None
    status: str = "active"
    data_quality_score: float | None = None


class SignalListResponse(BaseModel):
    items: list[SignalListItem]
    total: int
    page: int
    page_size: int


class SignalHistoryItem(BaseModel):
    id: str
    stock_code: str
    action: str
    confidence: float
    risk_level: str
    price_at: float | None = None
    reason: str
    signal_time: str | None = None
    valid_until: str | None = None
    status: str
    executed_at: str | None = None
    executed_price: float | None = None
    pnl: float | None = None
    pnl_pct: float | None = None
    data_quality_score: float | None = None


class SignalHistoryResponse(BaseModel):
    stock_code: str
    items: list[SignalHistoryItem]
    total: int
    days: int