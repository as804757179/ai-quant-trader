import asyncio
import os

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")

from app.ai.base_agent import BaseAgent
from app.ai.schemas import AgentStatus


class _SuccessAgent(BaseAgent):
    name = "test_success"
    model = "test-model"
    timeout_seconds = 1.0

    async def analyze(self, context: dict) -> dict:
        self.last_input_tokens = 10
        self.last_output_tokens = 5
        return {"confidence": 0.8, "reason": "ok", "code": context.get("code")}

    def get_neutral_result(self) -> dict:
        return self._mark_degraded(
            {"confidence": 0.0, "reason": "neutral"}
        )


class _SlowAgent(BaseAgent):
    name = "test_slow"
    model = "test-model"
    timeout_seconds = 0.05

    async def analyze(self, context: dict) -> dict:
        await asyncio.sleep(0.2)
        return {"confidence": 0.8}

    def get_neutral_result(self) -> dict:
        return self._mark_degraded(
            {"confidence": 0.0, "reason": "timeout neutral"}
        )


class _ErrorAgent(BaseAgent):
    name = "test_error"
    model = "test-model"
    timeout_seconds = 1.0

    async def analyze(self, context: dict) -> dict:
        raise RuntimeError("boom")

    def get_neutral_result(self) -> dict:
        return self._mark_degraded(
            {"confidence": 0.0, "reason": "error neutral"}
        )


def test_run_safe_success() -> None:
    agent = _SuccessAgent()
    result = asyncio.run(agent.run_safe({"code": "000001"}))
    assert result.status == AgentStatus.SUCCESS
    assert result.output["confidence"] == 0.8
    assert result.input_tokens == 10
    assert result.output_tokens == 5


def test_run_safe_timeout_degrades() -> None:
    agent = _SlowAgent()
    result = asyncio.run(agent.run_safe({"code": "000001"}))
    assert result.status == AgentStatus.TIMEOUT
    assert result.output["_degraded"] is True
    assert result.error_msg is not None


def test_run_safe_error_degrades() -> None:
    agent = _ErrorAgent()
    result = asyncio.run(agent.run_safe({"code": "000001"}))
    assert result.status == AgentStatus.ERROR
    assert result.output["_degraded"] is True


def test_parse_json_response_strips_markdown() -> None:
    agent = _SuccessAgent()
    parsed = agent._parse_json_response('```json\n{"trend": "UP"}\n```')
    assert parsed == {"trend": "UP"}


def test_build_market_context_str() -> None:
    agent = _SuccessAgent()
    text = agent._build_market_context_str(
        {"code": "000001", "name": "平安银行", "sector": "银行", "board": "主板", "price": 10.5}
    )
    assert "000001" in text
    assert "平安银行" in text