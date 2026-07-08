from __future__ import annotations

from typing import Any

import structlog

from app.ai.base_agent import BaseAgent
from app.ai.schemas import AgentResult, AgentStatus

logger = structlog.get_logger(__name__)


class RiskAgent(BaseAgent):
    """
    风控评估 Agent（规则引擎，不调用外部 LLM）。
    通过 context['agent_results'] 读取其他 Agent 输出并做风险评估。
    """

    name = "risk"
    model = "rule-engine"

    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        agent_results = context.get("agent_results", [])
        return self.evaluate(context, agent_results)

    def evaluate(
        self, context: dict[str, Any], agent_results: list[Any]
    ) -> dict[str, Any]:
        issues: list[str] = []
        score = 100

        rsi = float(context.get("rsi14") or 50)
        if rsi > 75:
            score -= 20
            issues.append(f"RSI={rsi:.1f}，股票处于超买区间，追高风险大")
        elif rsi < 25:
            score -= 10
            issues.append(f"RSI={rsi:.1f}，超卖区间，但下跌趋势中可能继续下跌")

        price_5d_change = float(context.get("price_5d_change") or 0)
        if price_5d_change > 20:
            score -= 25
            issues.append(
                f"5日涨幅{price_5d_change:.1f}%，短期涨幅过大，回调风险高"
            )

        volume_ratio = float(context.get("volume_ratio") or 1.0)
        trend_output = self._find_agent_output(agent_results, "trend")
        if trend_output and trend_output.get("trend") == "UP" and volume_ratio < 0.7:
            score -= 15
            issues.append("价格上涨但成交量萎缩，量价背离，趋势可信度低")

        if context.get("is_st", False):
            score = min(score, 20)
            issues.append("ST股票，风险极高，不建议操作")

        price = float(context.get("price") or 0)
        prev_close = float(context.get("prev_close") or price)
        if prev_close > 0 and price > 0:
            pct_to_limit = (prev_close * 1.10 - price) / price * 100
            if 0 < pct_to_limit < 2:
                score -= 20
                issues.append(f"距涨停板仅{pct_to_limit:.1f}%，追板风险极高")

        agent_confidences = [
            float(self._agent_output(r).get("confidence", 0.5))
            for r in agent_results
            if self._is_success(r) and not self._agent_output(r).get("_degraded")
        ]
        if len(agent_confidences) < 2:
            score -= 10
            issues.append("有效Agent不足，分析结果可信度降低")

        daily_amount = float(context.get("daily_amount") or 0)
        if 0 < daily_amount < 30_000_000:
            score -= 15
            issues.append(
                f"日成交额仅{daily_amount / 1e4:.0f}万，流动性不足，大单进出困难"
            )

        score = max(0, score)
        risk_level = (
            "LOW"
            if score >= 80
            else "MEDIUM"
            if score >= 60
            else "HIGH"
            if score >= 40
            else "EXTREME"
        )

        result = {
            "risk_score": score,
            "risk_level": risk_level,
            "issues": issues,
            "pass": risk_level not in ("HIGH", "EXTREME"),
            "confidence": 0.9,
            "reason": f"风控评分{score}分，风险等级{risk_level}。"
            + (
                "发现问题：" + "；".join(issues)
                if issues
                else "无明显风险因素。"
            ),
        }
        logger.info(
            "risk_evaluated",
            stock_code=context.get("code"),
            risk_score=score,
            risk_level=risk_level,
            issue_count=len(issues),
        )
        return result

    def get_neutral_result(self) -> dict[str, Any]:
        return {
            "risk_score": 50,
            "risk_level": "MEDIUM",
            "pass": True,
            "issues": [],
            "confidence": 0.5,
            "reason": "风控评估使用默认值",
            "_degraded": True,
        }

    @staticmethod
    def _agent_output(result: Any) -> dict[str, Any]:
        if isinstance(result, AgentResult):
            return result.output
        if isinstance(result, dict):
            return result.get("output", result)
        if hasattr(result, "output"):
            return result.output
        return {}

    @staticmethod
    def _is_success(result: Any) -> bool:
        if isinstance(result, AgentResult):
            return result.status == AgentStatus.SUCCESS
        if isinstance(result, dict):
            return result.get("status") == AgentStatus.SUCCESS.value
        status = getattr(result, "status", None)
        return status == AgentStatus.SUCCESS or status == AgentStatus.SUCCESS.value

    def _find_agent_output(
        self, agent_results: list[Any], name: str
    ) -> dict[str, Any] | None:
        for result in agent_results:
            agent_name = (
                result.agent_name
                if isinstance(result, AgentResult)
                else result.get("agent_name")
                if isinstance(result, dict)
                else getattr(result, "agent_name", None)
            )
            if agent_name == name:
                return self._agent_output(result)
        return None