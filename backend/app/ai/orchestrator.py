from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from app.ai.aggregator import SignalAggregator
from app.ai.fundamental_agent import FundamentalAgent
from app.ai.risk_agent import RiskAgent
from app.ai.schemas import AgentResult, AgentStatus
from app.ai.sentiment_agent import SentimentAgent
from app.ai.shortterm_agent import ShortTermAgent
from app.ai.trend_agent import TrendAgent
from app.rag.engine import RAGEngine

logger = structlog.get_logger(__name__)


class AgentOrchestrator:
    """
    多 Agent 并发调度器。

    流程：4 个 LLM Agent 并行 run_safe → RiskAgent.evaluate → SignalAggregator
    """

    ORCHESTRATOR_TIMEOUT = 45

    def __init__(
        self,
        trend_agent: TrendAgent | None = None,
        fundamental_agent: FundamentalAgent | None = None,
        sentiment_agent: SentimentAgent | None = None,
        shortterm_agent: ShortTermAgent | None = None,
        risk_agent: RiskAgent | None = None,
        aggregator: SignalAggregator | None = None,
        rag_engine: RAGEngine | None = None,
    ) -> None:
        self.trend_agent = trend_agent or TrendAgent()
        self.fundamental_agent = fundamental_agent or FundamentalAgent()
        self.sentiment_agent = sentiment_agent or SentimentAgent()
        self.shortterm_agent = shortterm_agent or ShortTermAgent()
        self.risk_agent = risk_agent or RiskAgent()
        self.aggregator = aggregator or SignalAggregator()
        self.rag_engine = rag_engine or RAGEngine()

    async def run(self, code: str, context: dict[str, Any]) -> dict[str, Any]:
        """完整分析流程：并行调度 Agent → 风控评估 → 信号聚合。"""
        run_context = {**context, "code": code}
        if run_context.get("analysis_context_status") != "ready":
            return self._blocked_context_result(code, run_context)
        if "rag_context" not in run_context:
            run_context["rag_context"] = await self.rag_engine.build_rag_context(
                code
            )
        start = time.perf_counter()

        logger.info("orchestrator_start", stock_code=code)

        llm_specs: list[tuple[str, Any]] = [
            ("trend", self.trend_agent),
            ("fundamental", self.fundamental_agent),
            ("sentiment", self.sentiment_agent),
            ("shortterm", self.shortterm_agent),
        ]

        llm_results: list[AgentResult] = await asyncio.gather(
            *[agent.run_safe(run_context) for _, agent in llm_specs]
        )

        agent_results: dict[str, AgentResult] = {}
        for (name, _), result in zip(llm_specs, llm_results):
            agent_results[name] = result
            logger.info(
                "agent_completed",
                stock_code=code,
                agent=name,
                status=result.status,
                latency_ms=result.latency_ms,
                degraded=bool(result.output.get("_degraded")),
            )

        risk_start = time.perf_counter()
        risk_output = self.risk_agent.evaluate(run_context, llm_results)
        risk_latency = int((time.perf_counter() - risk_start) * 1000)
        risk_result = AgentResult(
            agent_name="risk",
            model=self.risk_agent.model,
            output=risk_output,
            status=AgentStatus.SUCCESS,
            latency_ms=risk_latency,
            input_tokens=0,
            output_tokens=0,
        )
        agent_results["risk"] = risk_result
        logger.info(
            "agent_completed",
            stock_code=code,
            agent="risk",
            status=risk_result.status,
            latency_ms=risk_latency,
            risk_level=risk_output.get("risk_level"),
        )

        signal = self.aggregator.aggregate(
            agent_results,
            stock_code=code,
            current_price=float(run_context.get("price") or 0),
        )

        total_latency_ms = int((time.perf_counter() - start) * 1000)
        agent_statuses = {
            name: result.status for name, result in agent_results.items()
        }

        logger.info(
            "orchestrator_done",
            stock_code=code,
            action=signal.get("action"),
            confidence=signal.get("confidence"),
            latency_ms=total_latency_ms,
            agent_statuses=agent_statuses,
        )

        return {
            "code": code,
            "signal": signal,
            "agent_results": agent_results,
            "agent_statuses": agent_statuses,
            "latency_ms": total_latency_ms,
        }

    def _blocked_context_result(
        self, code: str, context: dict[str, Any]
    ) -> dict[str, Any]:
        blockers = context.get("analysis_context_blockers") or []
        source_names = sorted(
            {
                str(item.get("source"))
                for item in blockers
                if isinstance(item, dict) and item.get("source")
            }
        )
        source_summary = ", ".join(source_names) if source_names else "未声明的关键数据源"
        reason = (
            f"AI 分析上下文未通过数据与研究资格门禁：{source_summary}。"
            "不调用模型，仅返回 HOLD。"
        )
        agent_results = {
            name: AgentResult(
                agent_name=name,
                model="not-run",
                output={"_degraded": True, "reason": reason},
                status=AgentStatus.DEGRADED,
                latency_ms=0,
                error_msg="analysis context gate blocked",
            )
            for name in ("trend", "fundamental", "sentiment", "shortterm", "risk")
        }
        try:
            current_price = float(context.get("price") or 0)
        except (TypeError, ValueError):
            current_price = 0.0
        signal = self.aggregator.aggregate(
            agent_results,
            stock_code=code,
            current_price=current_price,
        )
        signal["reason"] = reason
        signal["confidence"] = 0.0
        return {
            "code": code,
            "signal": signal,
            "agent_results": agent_results,
            "agent_statuses": {
                name: result.status for name, result in agent_results.items()
            },
            "latency_ms": 0,
        }

    async def analyze(self, code: str, context: dict[str, Any]) -> dict[str, Any]:
        """文档兼容别名，返回聚合后的 signal 字典。"""
        result = await self.run(code, context)
        return result["signal"]
