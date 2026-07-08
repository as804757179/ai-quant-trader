import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://quant_admin:pass@localhost:5432/quant_trader",
)
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")

from app.ai.schemas import AgentResult, AgentStatus
from app.api.ai import get_ai_service
from app.main import app
from app.schemas.ai import (
    AgentResultSummary,
    AnalyzeResponseData,
    SignalHistoryResponse,
    SignalListResponse,
    SignalPayload,
)
from app.services.ai_service import AIService, AnalysisError


def _sample_orchestrator_result() -> dict[str, Any]:
    return {
        "code": "000001",
        "signal": {
            "id": "11111111-1111-1111-1111-111111111111",
            "action": "BUY",
            "confidence": 0.72,
            "raw_confidence": 0.75,
            "risk_level": "LOW",
            "price_at": 10.5,
            "reason": "趋势向上；基本面良好",
            "scores": {
                "trend": 0.8,
                "fundamental": 0.7,
                "sentiment": 0.65,
                "shortterm": 0.6,
                "risk": 0.9,
            },
            "degraded_agents": [],
            "signal_time": "2026-07-08T10:00:00",
            "valid_until": "2026-07-09T10:00:00",
        },
        "agent_results": {
            "trend": AgentResult(
                agent_name="trend",
                model="gpt-4o",
                output={"trend": "UP", "confidence": 0.8},
                status=AgentStatus.SUCCESS,
                latency_ms=100,
            ),
            "fundamental": AgentResult(
                agent_name="fundamental",
                model="claude",
                output={"overall_score": 75, "confidence": 0.75},
                status=AgentStatus.SUCCESS,
                latency_ms=120,
            ),
            "sentiment": AgentResult(
                agent_name="sentiment",
                model="qwen",
                output={"sentiment": "POSITIVE", "confidence": 0.7},
                status=AgentStatus.SUCCESS,
                latency_ms=90,
            ),
            "shortterm": AgentResult(
                agent_name="shortterm",
                model="deepseek",
                output={"short_term_signal": "HOLD", "confidence": 0.6},
                status=AgentStatus.SUCCESS,
                latency_ms=80,
            ),
            "risk": AgentResult(
                agent_name="risk",
                model="rule-engine",
                output={"risk_score": 90, "risk_level": "LOW", "pass": True},
                status=AgentStatus.SUCCESS,
                latency_ms=5,
            ),
        },
        "agent_statuses": {
            "trend": "success",
            "fundamental": "success",
            "sentiment": "success",
            "shortterm": "success",
            "risk": "success",
        },
        "latency_ms": 500,
    }


def _degraded_orchestrator_result() -> dict[str, Any]:
    result = _sample_orchestrator_result()
    result["signal"]["action"] = "HOLD"
    result["signal"]["confidence"] = 0.55
    result["signal"]["degraded_agents"] = ["sentiment"]
    result["agent_results"]["sentiment"] = AgentResult(
        agent_name="sentiment",
        model="qwen",
        output={
            "sentiment": "NEUTRAL",
            "confidence": 0.0,
            "_degraded": True,
        },
        status=AgentStatus.TIMEOUT,
        latency_ms=30000,
        error_msg="Timeout",
    )
    result["agent_statuses"]["sentiment"] = "timeout"
    return result


class _MockAIService(AIService):
    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self._result = result or _sample_orchestrator_result()
        self.saved = False

    async def close(self) -> None:
        return None

    async def get_valid_signal(self, code: str) -> AnalyzeResponseData | None:
        return None

    async def analyze(self, code: str, **kwargs: Any) -> AnalyzeResponseData:
        signal_id = "22222222-2222-2222-2222-222222222222"
        self.saved = True
        signal_data = self._result["signal"]
        return AnalyzeResponseData(
            code=code,
            signal=SignalPayload(
                id=signal_id,
                action=signal_data["action"],
                confidence=signal_data["confidence"],
                raw_confidence=signal_data.get("raw_confidence"),
                risk_level=signal_data["risk_level"],
                price_at=signal_data.get("price_at"),
                reason=signal_data["reason"],
                scores=signal_data.get("scores", {}),
                degraded_agents=signal_data.get("degraded_agents", []),
            ),
            scores=signal_data.get("scores", {}),
            reason=signal_data["reason"],
            agent_results={
                "trend": AgentResultSummary(
                    agent_name="trend",
                    model="gpt-4o",
                    status="success",
                    latency_ms=100,
                    output={"trend": "UP"},
                )
            },
            agent_statuses=self._result.get("agent_statuses", {}),
            latency_ms=self._result.get("latency_ms", 0),
            signal_id=signal_id,
            data_quality_score=90.0,
        )


async def _request(method: str, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path)


def test_analyze_endpoint_success() -> None:
    mock_svc = _MockAIService()
    app.dependency_overrides[get_ai_service] = lambda: mock_svc

    response = asyncio.run(_request("POST", "/api/v1/ai/000001/analyze"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["code"] == "000001"
    assert payload["data"]["signal"]["action"] == "BUY"
    assert payload["data"]["scores"]["trend"] == 0.8
    assert mock_svc.saved is True

    app.dependency_overrides.clear()


def test_analyze_endpoint_degraded_agents() -> None:
    mock_svc = _MockAIService(_degraded_orchestrator_result())
    app.dependency_overrides[get_ai_service] = lambda: mock_svc

    response = asyncio.run(_request("POST", "/api/v1/ai/000001/analyze"))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["signal"]["action"] == "HOLD"
    assert "sentiment" in data["signal"]["degraded_agents"]

    app.dependency_overrides.clear()


def test_ai_service_save_signal() -> None:
    async def _run() -> None:
        svc = AIService(
            data_service=MagicMock(),
            orchestrator=MagicMock(),
        )
        result = _sample_orchestrator_result()

        mock_db = AsyncMock()
        insert_result = MagicMock()
        insert_result.scalar_one.return_value = (
            "33333333-3333-3333-3333-333333333333"
        )
        mock_db.execute = AsyncMock(return_value=insert_result)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.ai_service.get_db", return_value=mock_cm):
            signal_id = await svc._save_signal(
                code="000001",
                result=result,
                strategy_id=1,
                data_quality_score=88.5,
            )

        assert signal_id == "33333333-3333-3333-3333-333333333333"
        assert mock_db.execute.await_count >= 2

    asyncio.run(_run())


class _MockAIServiceWithCache(_MockAIService):
    def __init__(self) -> None:
        super().__init__()
        self.analyze_calls = 0

    async def analyze(self, code: str, **kwargs: Any) -> AnalyzeResponseData:
        self.analyze_calls += 1
        if not kwargs.get("force_refresh"):
            return AnalyzeResponseData(
                code=code,
                signal=SignalPayload(
                    action="HOLD",
                    confidence=0.5,
                    risk_level="MEDIUM",
                    reason="cached",
                ),
                scores={},
                reason="cached",
                agent_results={},
                from_cache=True,
                signal_id="cache-id",
            )
        return await super().analyze(code, **kwargs)


def test_analyze_invalid_stock_code() -> None:
    async def _run() -> None:
        svc = AIService(data_service=MagicMock(), orchestrator=MagicMock())
        with patch.object(svc, "_stock_exists", AsyncMock(return_value=False)):
            try:
                await svc.analyze("999999")
                raise AssertionError("expected AnalysisError")
            except AnalysisError as exc:
                assert exc.status_code == 404

    asyncio.run(_run())


def test_analyze_invalid_code_format() -> None:
    async def _run() -> None:
        svc = AIService(data_service=MagicMock(), orchestrator=MagicMock())
        try:
            await svc.analyze("ABC")
            raise AssertionError("expected AnalysisError")
        except AnalysisError as exc:
            assert exc.status_code == 400

    asyncio.run(_run())


class _FailingAIService:
    async def close(self) -> None:
        return None

    async def analyze(self, code: str, **kwargs: Any) -> AnalyzeResponseData:
        raise AnalysisError("股票代码 999999 不存在", 404)


def test_analyze_endpoint_invalid_code_returns_404() -> None:
    app.dependency_overrides[get_ai_service] = lambda: _FailingAIService()
    response = asyncio.run(_request("POST", "/api/v1/ai/999999/analyze"))
    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_force_refresh_skips_cache() -> None:
    mock_svc = _MockAIServiceWithCache()
    app.dependency_overrides[get_ai_service] = lambda: mock_svc

    asyncio.run(_request("POST", "/api/v1/ai/000001/analyze"))
    assert mock_svc.analyze_calls == 1

    asyncio.run(
        _request("POST", "/api/v1/ai/000001/analyze?force_refresh=true")
    )
    assert mock_svc.analyze_calls == 2

    app.dependency_overrides.clear()


def test_list_signals_endpoint() -> None:
    mock_svc = AIService(data_service=MagicMock(), orchestrator=MagicMock())
    mock_svc.list_signals = AsyncMock(  # type: ignore[method-assign]
        return_value=SignalListResponse(
            items=[],
            total=0,
            page=1,
            page_size=50,
        )
    )
    mock_svc.close = AsyncMock()  # type: ignore[method-assign]

    app.dependency_overrides[get_ai_service] = lambda: mock_svc
    response = asyncio.run(_request("GET", "/api/v1/ai/signals?action=BUY"))
    assert response.status_code == 200
    assert response.json()["data"]["total"] == 0
    app.dependency_overrides.clear()


def test_full_analyze_pipeline_with_mocks() -> None:
    """端到端链路：context → orchestrator → 落库 → 响应（全 Mock）。"""

    async def _run() -> None:
        mock_data = MagicMock()
        mock_data.get_full_context = AsyncMock(
            return_value={"code": "000001", "price": 10.5, "data_quality_score": 85.0}
        )
        mock_data.close = AsyncMock()

        mock_orch = MagicMock()
        mock_orch.run = AsyncMock(return_value=_sample_orchestrator_result())

        svc = AIService(data_service=mock_data, orchestrator=mock_orch)
        with (
            patch.object(svc, "_stock_exists", AsyncMock(return_value=True)),
            patch.object(svc, "_save_signal", AsyncMock(return_value="saved-signal-id")),
        ):
            result = await svc.analyze("000001", force_refresh=True)

        assert result.signal.action == "BUY"
        assert result.signal_id == "saved-signal-id"
        assert result.data_quality_score == 85.0
        mock_orch.run.assert_awaited_once()

    asyncio.run(_run())


def test_signal_history_endpoint() -> None:
    mock_svc = AIService(data_service=MagicMock(), orchestrator=MagicMock())
    mock_svc.get_signal_history = AsyncMock(  # type: ignore[method-assign]
        return_value=SignalHistoryResponse(
            stock_code="000001",
            items=[],
            total=0,
            days=30,
        )
    )
    mock_svc.close = AsyncMock()  # type: ignore[method-assign]

    app.dependency_overrides[get_ai_service] = lambda: mock_svc
    response = asyncio.run(_request("GET", "/api/v1/ai/000001/signal-history"))
    assert response.status_code == 200
    assert response.json()["data"]["stock_code"] == "000001"
    app.dependency_overrides.clear()