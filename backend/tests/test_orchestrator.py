import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")

from app.ai.aggregator import SignalAggregator
from app.ai.orchestrator import AgentOrchestrator
from app.ai.schemas import AgentResult, AgentStatus


def _sample_context() -> dict[str, Any]:
    return {
        "code": "000001",
        "name": "平安银行",
        "price": 10.5,
        "prev_close": 10.0,
        "rsi14": 55,
        "volume_ratio": 1.2,
        "price_5d_change": 5.0,
        "daily_amount": 500_000_000,
    }


def _agent_result(
    name: str,
    output: dict[str, Any],
    status: AgentStatus = AgentStatus.SUCCESS,
) -> AgentResult:
    return AgentResult(
        agent_name=name,
        model=f"mock-{name}",
        output=output,
        status=status,
        latency_ms=50,
    )


class _MockAgent:
    def __init__(self, name: str, model: str, output: dict[str, Any]) -> None:
        self.name = name
        self.model = model
        self._output = output

    async def run_safe(self, context: dict[str, Any]) -> AgentResult:
        return _agent_result(self.name, self._output)


class _MockRAGEngine:
    async def build_rag_context(self, stock_code: str) -> dict[str, str]:
        return {"research": "", "announcements": "", "news": ""}


class _TimeoutAgent:
    name = "sentiment"
    model = "mock-sentiment"

    async def run_safe(self, context: dict[str, Any]) -> AgentResult:
        return AgentResult(
            agent_name=self.name,
            model=self.model,
            output={
                "sentiment": "NEUTRAL",
                "sentiment_score": 50,
                "heat_score": 50,
                "confidence": 0.0,
                "reason": "情绪分析不可用（服务超时或错误）",
                "_degraded": True,
            },
            status=AgentStatus.TIMEOUT,
            latency_ms=30000,
            error_msg="Timeout",
        )


def test_orchestrator_parallel_run() -> None:
    orchestrator = AgentOrchestrator(
        rag_engine=_MockRAGEngine(),
        trend_agent=_MockAgent(
            "trend",
            "gpt-4o",
            {"trend": "UP", "trend_strength": 0.8, "confidence": 0.8},
        ),
        fundamental_agent=_MockAgent(
            "fundamental",
            "claude",
            {
                "overall_score": 75,
                "grade": "B+",
                "growth_outlook": "UP",
                "confidence": 0.75,
            },
        ),
        sentiment_agent=_MockAgent(
            "sentiment",
            "qwen",
            {
                "sentiment": "POSITIVE",
                "heat_score": 70,
                "confidence": 0.7,
            },
        ),
        shortterm_agent=_MockAgent(
            "shortterm",
            "deepseek",
            {"short_term_signal": "BUY", "confidence": 0.7},
        ),
    )

    result = asyncio.run(orchestrator.run("000001", _sample_context()))

    assert result["code"] == "000001"
    assert len(result["agent_results"]) == 5
    assert result["agent_results"]["risk"].status == AgentStatus.SUCCESS
    assert result["signal"]["action"] in ("BUY", "SELL", "HOLD")
    assert "scores" in result["signal"]
    assert "reason" in result["signal"]
    assert result["latency_ms"] >= 0


def test_orchestrator_partial_timeout() -> None:
    orchestrator = AgentOrchestrator(
        rag_engine=_MockRAGEngine(),
        trend_agent=_MockAgent(
            "trend",
            "gpt-4o",
            {"trend": "UP", "trend_strength": 0.7, "confidence": 0.7},
        ),
        fundamental_agent=_MockAgent(
            "fundamental",
            "claude",
            {
                "overall_score": 60,
                "grade": "B",
                "growth_outlook": "STABLE",
                "confidence": 0.6,
            },
        ),
        sentiment_agent=_TimeoutAgent(),
        shortterm_agent=_MockAgent(
            "shortterm",
            "deepseek",
            {"short_term_signal": "HOLD", "confidence": 0.5},
        ),
    )

    result = asyncio.run(orchestrator.run("000001", _sample_context()))

    assert result["agent_statuses"]["sentiment"] == AgentStatus.TIMEOUT
    assert "sentiment" in result["signal"]["degraded_agents"]
    assert result["signal"]["confidence"] <= result["signal"]["raw_confidence"]


def test_aggregator_buy_signal() -> None:
    aggregator = SignalAggregator()
    results = {
        "trend": _agent_result(
            "trend",
            {"trend": "UP", "trend_strength": 0.9, "confidence": 0.85},
        ),
        "fundamental": _agent_result(
            "fundamental",
            {
                "overall_score": 85,
                "grade": "A",
                "growth_outlook": "UP",
                "confidence": 0.8,
            },
        ),
        "sentiment": _agent_result(
            "sentiment",
            {"sentiment": "POSITIVE", "heat_score": 80, "confidence": 0.8},
        ),
        "shortterm": _agent_result(
            "shortterm",
            {"short_term_signal": "BUY", "confidence": 0.75},
        ),
        "risk": _agent_result(
            "risk",
            {
                "risk_score": 90,
                "risk_level": "LOW",
                "pass": True,
                "issues": [],
                "confidence": 0.9,
            },
        ),
    }

    signal = aggregator.aggregate(results, "000001", 10.5)

    assert signal["action"] == "BUY"
    assert signal["scores"]["trend"] > 0.7
    assert signal["signal"]["confidence"] > 0


def test_aggregator_extreme_risk_blocks_signal() -> None:
    aggregator = SignalAggregator()
    results = {
        "trend": _agent_result(
            "trend",
            {"trend": "UP", "trend_strength": 0.9, "confidence": 0.9},
        ),
        "fundamental": _agent_result(
            "fundamental",
            {"overall_score": 90, "grade": "A", "growth_outlook": "UP"},
        ),
        "sentiment": _agent_result(
            "sentiment",
            {"sentiment": "POSITIVE", "heat_score": 90},
        ),
        "shortterm": _agent_result(
            "shortterm",
            {"short_term_signal": "BUY", "confidence": 0.9},
        ),
        "risk": _agent_result(
            "risk",
            {
                "risk_score": 15,
                "risk_level": "EXTREME",
                "pass": False,
                "issues": ["ST股票，风险极高，不建议操作"],
            },
        ),
    }

    signal = aggregator.aggregate(results, "000001", 10.5)

    assert signal["action"] == "HOLD"
    assert signal["risk_level"] == "EXTREME"
    assert signal["confidence"] <= 0.15


def test_aggregator_degraded_weight_redistribution() -> None:
    aggregator = SignalAggregator()
    degraded = aggregator._find_degraded_agents(
        {
            "trend": _agent_result(
                "trend",
                {"trend": "UP", "_degraded": True},
            ),
            "fundamental": _agent_result(
                "fundamental",
                {"overall_score": 70, "growth_outlook": "UP"},
            ),
        }
    )
    weights = aggregator._adjust_weights_for_degraded(degraded)

    assert "trend" in degraded
    assert weights["trend"] == 0.0
    assert weights["fundamental"] > aggregator.WEIGHTS["fundamental"]