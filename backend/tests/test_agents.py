import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")

from app.ai.fundamental_agent import FundamentalAgent
from app.ai.risk_agent import RiskAgent
from app.ai.schemas import AgentResult, AgentStatus
from app.ai.sentiment_agent import SentimentAgent
from app.ai.shortterm_agent import ShortTermAgent
from app.ai.trend_agent import TrendAgent


def _sample_context() -> dict:
    return {
        "code": "000001",
        "name": "平安银行",
        "sector": "银行",
        "board": "主板",
        "price": 10.5,
        "prev_close": 10.0,
        "rsi14": 55,
        "volume_ratio": 1.2,
        "turnover_rate": 1.5,
        "price_changes_5d": "+2.3%",
        "price_5d_change": 5.0,
        "daily_amount": 500_000_000,
        "financial_report": {
            "report_date": "2024-12-31",
            "publish_date": "2025-04-01",
            "revenue": 1_200_000_000,
            "revenue_yoy": 12.5,
            "net_profit": 300_000_000,
            "profit_yoy": 8.0,
            "gross_margin": 35.0,
            "roe": 12.0,
            "debt_ratio": 45.0,
            "oper_cashflow": 200_000_000,
            "pe_ratio": 8.5,
            "pb_ratio": 0.9,
            "eps": 1.2,
        },
        "news": [
            {"publish_time": "2026-07-07", "title": "业绩超预期"},
        ],
        "fund_flow": {"main_net_in": 50_000_000, "super_large_in": 20_000_000},
        "north_flow": {"today": 10_000_000, "five_day": 80_000_000},
        "dragon_tiger": [{"trader": "机构专用", "side": "买入", "amount": "5000万"}],
        "today_kline": {"open": 10.2, "high": 10.8, "low": 10.1},
        "kline_5m": [{"close": 10.4}, {"close": 10.5}],
        "kline_15m": [{"close": 10.3}, {"close": 10.5}],
    }


def _mock_openai_response(payload: str) -> MagicMock:
    usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    message = MagicMock(content=payload)
    choice = MagicMock(message=message)
    response = MagicMock(usage=usage, choices=[choice])
    return response


def _mock_anthropic_response(payload: str) -> MagicMock:
    usage = MagicMock(input_tokens=120, output_tokens=60)
    block = MagicMock(type="text", text=payload)
    response = MagicMock(usage=usage, content=[block])
    return response


def test_trend_agent_neutral_result() -> None:
    agent = TrendAgent()
    result = agent.get_neutral_result()
    assert result["trend"] == "SIDEWAYS"
    assert result["_degraded"] is True


def test_fundamental_agent_neutral_result() -> None:
    agent = FundamentalAgent()
    result = agent.get_neutral_result()
    assert result["overall_score"] == 50
    assert result["_degraded"] is True


def test_sentiment_agent_format_helpers() -> None:
    agent = SentimentAgent()
    assert "暂无" in agent._format_news([])
    assert "龙虎榜" in agent._format_dragon_tiger([])


def test_shortterm_agent_limit_distance() -> None:
    agent = ShortTermAgent()
    up, down = agent._calc_limit_distance(10.0, 10.0)
    assert up == "10.0"
    assert down == "10.0"


def test_risk_agent_low_risk() -> None:
    agent = RiskAgent()
    context = _sample_context()
    trend = AgentResult(
        agent_name="trend",
        model="gpt-4o",
        output={"trend": "UP", "confidence": 0.8},
        status=AgentStatus.SUCCESS,
        latency_ms=100,
    )
    fundamental = AgentResult(
        agent_name="fundamental",
        model="claude",
        output={"confidence": 0.7},
        status=AgentStatus.SUCCESS,
        latency_ms=100,
    )
    result = agent.evaluate(context, [trend, fundamental])
    assert result["risk_level"] == "LOW"
    assert result["pass"] is True


def test_risk_agent_extreme_st_stock() -> None:
    agent = RiskAgent()
    context = {**_sample_context(), "is_st": True}
    result = agent.evaluate(context, [])
    assert result["risk_level"] == "EXTREME"
    assert result["pass"] is False


def test_risk_agent_volume_divergence() -> None:
    agent = RiskAgent()
    context = {**_sample_context(), "volume_ratio": 0.5}
    trend = AgentResult(
        agent_name="trend",
        model="gpt-4o",
        output={"trend": "UP", "confidence": 0.8},
        status=AgentStatus.SUCCESS,
        latency_ms=100,
    )
    fundamental = AgentResult(
        agent_name="fundamental",
        model="claude",
        output={"confidence": 0.7},
        status=AgentStatus.SUCCESS,
        latency_ms=100,
    )
    result = agent.evaluate(context, [trend, fundamental])
    assert any("量价背离" in issue for issue in result["issues"])


def test_risk_agent_run_safe() -> None:
    agent = RiskAgent()
    context = _sample_context()
    context["agent_results"] = []
    result = asyncio.run(agent.run_safe(context))
    assert result.status == AgentStatus.SUCCESS
    assert "risk_score" in result.output


@patch("app.ai.trend_agent.AsyncOpenAI")
def test_trend_agent_analyze_mock(mock_client_cls: MagicMock) -> None:
    payload = (
        '{"trend":"UP","trend_strength":0.8,"confidence":0.75,'
        '"reason":"多头排列"}'
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_openai_response(payload)
    )
    mock_client_cls.return_value = mock_client

    agent = TrendAgent()
    output = asyncio.run(agent.analyze(_sample_context()))
    assert output["trend"] == "UP"
    assert agent.last_input_tokens == 100


@patch("app.ai.fundamental_agent.anthropic.AsyncAnthropic")
@patch("app.ai.fundamental_agent.RAGEngine")
def test_fundamental_agent_analyze_mock(
    mock_rag_cls: MagicMock, mock_client_cls: MagicMock
) -> None:
    mock_rag = MagicMock()
    mock_rag.retrieve_research = AsyncMock(return_value="研报摘要")
    mock_rag.retrieve_announcements = AsyncMock(return_value="公告摘要")
    mock_rag_cls.return_value = mock_rag

    payload = (
        '{"overall_score":72,"grade":"B+","growth_outlook":"UP",'
        '"confidence":0.8,"reason":"基本面良好"}'
    )
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        return_value=_mock_anthropic_response(payload)
    )
    mock_client_cls.return_value = mock_client

    agent = FundamentalAgent()
    output = asyncio.run(agent.analyze(_sample_context()))
    assert output["overall_score"] == 72
    assert output["grade"] == "B+"


@patch("app.ai.sentiment_agent.AsyncOpenAI")
def test_sentiment_agent_analyze_mock(mock_client_cls: MagicMock) -> None:
    payload = (
        '{"sentiment":"POSITIVE","sentiment_score":70,"heat_score":65,'
        '"confidence":0.7,"reason":"情绪偏积极"}'
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_openai_response(payload)
    )
    mock_client_cls.return_value = mock_client

    agent = SentimentAgent()
    output = asyncio.run(agent.analyze(_sample_context()))
    assert output["sentiment"] == "POSITIVE"


@patch("app.ai.shortterm_agent.AsyncOpenAI")
def test_shortterm_agent_analyze_mock(mock_client_cls: MagicMock) -> None:
    payload = (
        '{"short_term_signal":"HOLD","confidence":0.6,'
        '"reason":"震荡整理"}'
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_openai_response(payload)
    )
    mock_client_cls.return_value = mock_client

    agent = ShortTermAgent()
    output = asyncio.run(agent.analyze(_sample_context()))
    assert output["short_term_signal"] == "HOLD"