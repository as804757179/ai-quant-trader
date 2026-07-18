from __future__ import annotations

import statistics
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from app.ai.schemas import AgentResult, AgentStatus
from app.core.config import settings

logger = structlog.get_logger(__name__)


class SignalAggregator:
    """
    加权聚合各 Agent 结果，生成最终交易信号。

    权重：趋势 30% + 基本面 25% + 情绪 20% + 短线 15% + 风控 10%
    """

    WEIGHTS: dict[str, float] = {
        "trend": 0.30,
        "fundamental": 0.25,
        "sentiment": 0.20,
        "shortterm": 0.15,
        "risk": 0.10,
    }

    def __init__(self) -> None:
        self.buy_threshold = settings.SIGNAL_BUY_THRESHOLD
        self.sell_threshold = settings.SIGNAL_SELL_THRESHOLD
        self.validity_hours = settings.SIGNAL_VALIDITY_HOURS
        self.min_confidence = settings.SIGNAL_MIN_CONFIDENCE

    def aggregate(
        self,
        results: dict[str, Any],
        stock_code: str,
        current_price: float,
    ) -> dict[str, Any]:
        scores = {
            "trend": self._trend_to_score(self._get_output(results.get("trend"))),
            "fundamental": self._fundamental_to_score(
                self._get_output(results.get("fundamental"))
            ),
            "sentiment": self._sentiment_to_score(
                self._get_output(results.get("sentiment"))
            ),
            "shortterm": self._shortterm_to_score(
                self._get_output(results.get("shortterm"))
            ),
            "risk": self._risk_to_score(self._get_output(results.get("risk"))),
        }

        risk_output = self._get_output(results.get("risk"))
        if risk_output.get("risk_level") == "EXTREME":
            signal = self._build_signal(
                stock_code=stock_code,
                action="HOLD",
                raw_confidence=0.1,
                calibrated_confidence=0.1,
                risk_level="EXTREME",
                current_price=current_price,
                reason="风控评级EXTREME，屏蔽所有交易信号",
                results=results,
                scores=scores,
            )
            logger.info(
                "aggregation_done",
                stock_code=stock_code,
                action="HOLD",
                risk_level="EXTREME",
                blocked=True,
            )
            return signal

        degraded_agents = self._find_degraded_agents(results)
        if degraded_agents:
            signal = self._build_signal(
                stock_code=stock_code,
                action="HOLD",
                raw_confidence=0.5,
                calibrated_confidence=0.0,
                risk_level=risk_output.get("risk_level", "UNKNOWN"),
                current_price=current_price,
                reason=f"关键分析子源不可用或降级: {', '.join(degraded_agents)}，仅返回HOLD",
                results=results,
                scores=scores,
                degraded_agents=degraded_agents,
            )
            logger.warning(
                "aggregation_degraded_hold",
                stock_code=stock_code,
                degraded_agents=degraded_agents,
            )
            return signal

        composite_score = sum(scores[name] * self.WEIGHTS[name] for name in scores)

        if composite_score >= self.buy_threshold:
            action = "BUY"
        elif composite_score <= self.sell_threshold:
            action = "SELL"
        else:
            action = "HOLD"

        calibrated = self._calibrate_confidence(
            raw_confidence=composite_score,
            results=results,
            degraded_agents=degraded_agents,
            risk_output=risk_output,
        )

        if action == "BUY" and calibrated < self.min_confidence:
            action = "HOLD"

        reason = self._build_reason(action, results, scores)
        risk_level = risk_output.get("risk_level", "MEDIUM")

        signal = self._build_signal(
            stock_code=stock_code,
            action=action,
            raw_confidence=composite_score,
            calibrated_confidence=calibrated,
            risk_level=risk_level,
            current_price=current_price,
            reason=reason,
            results=results,
            scores=scores,
            degraded_agents=degraded_agents,
        )
        logger.info(
            "aggregation_done",
            stock_code=stock_code,
            action=action,
            raw_confidence=round(composite_score, 4),
            calibrated_confidence=round(calibrated, 4),
            degraded_count=len(degraded_agents),
        )
        return signal

    def _build_signal(
        self,
        stock_code: str,
        action: str,
        raw_confidence: float,
        calibrated_confidence: float,
        risk_level: str,
        current_price: float,
        reason: str,
        results: dict[str, Any],
        scores: dict[str, float],
        degraded_agents: list[str] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        return {
            "id": str(uuid.uuid4()),
            "stock_code": stock_code,
            "signal": {
                "action": action,
                "confidence": round(calibrated_confidence, 4),
                "raw_confidence": round(raw_confidence, 4),
                "risk_level": risk_level,
            },
            "action": action,
            "confidence": round(calibrated_confidence, 4),
            "raw_confidence": round(raw_confidence, 4),
            "risk_level": risk_level,
            "price_at": current_price,
            "reason": reason,
            "scores": scores,
            "degraded_agents": degraded_agents or [],
            "agent_votes": {
                name: self._get_output(result) for name, result in results.items()
            },
            "signal_time": now.isoformat(),
            "valid_until": (now + timedelta(hours=self.validity_hours)).isoformat(),
        }

    def _calibrate_confidence(
        self,
        raw_confidence: float,
        results: dict[str, Any],
        degraded_agents: list[str],
        risk_output: dict[str, Any],
    ) -> float:
        calibrated = raw_confidence

        if degraded_agents:
            calibrated *= max(0.5, 1.0 - 0.08 * len(degraded_agents))

        confidences = []
        for name in ("trend", "fundamental", "sentiment", "shortterm"):
            output = self._get_output(results.get(name))
            if output and not output.get("_degraded"):
                confidences.append(float(output.get("confidence", 0.5)))

        if len(confidences) >= 2:
            spread = statistics.pstdev(confidences)
            if spread > 0.25:
                calibrated *= 0.85

        if not risk_output.get("pass", True):
            calibrated *= 0.75

        if risk_output.get("risk_level") == "HIGH":
            calibrated *= 0.9

        return max(0.0, min(1.0, calibrated))

    @staticmethod
    def _get_output(result: Any) -> dict[str, Any]:
        if result is None:
            return {}
        if isinstance(result, AgentResult):
            return result.output
        if hasattr(result, "output"):
            return result.output
        if isinstance(result, dict) and "output" in result:
            return result["output"]
        return result if isinstance(result, dict) else {}

    def _find_degraded_agents(self, results: dict[str, Any]) -> list[str]:
        degraded: list[str] = []
        for name in self.WEIGHTS:
            result = results.get(name)
            output = self._get_output(result)
            if (
                result is None
                or output.get("_degraded")
                or (
                    isinstance(result, AgentResult)
                    and result.status != AgentStatus.SUCCESS
                )
            ):
                degraded.append(name)
        return degraded

    def _trend_to_score(self, output: dict[str, Any]) -> float:
        if output.get("_degraded"):
            return 0.5
        trend_map = {"UP": 1.0, "SIDEWAYS": 0.5, "DOWN": 0.0}
        base = trend_map.get(output.get("trend", "SIDEWAYS"), 0.5)
        strength = float(output.get("trend_strength", 0.5))
        confidence = float(output.get("confidence", 0.5))
        return (base * 0.6 + strength * 0.4) * (0.5 + confidence * 0.5)

    def _fundamental_to_score(self, output: dict[str, Any]) -> float:
        if output.get("_degraded"):
            return 0.5
        score = float(output.get("overall_score", 50)) / 100.0
        growth = {"UP": 1.0, "STABLE": 0.5, "DOWN": 0.0}.get(
            output.get("growth_outlook", "STABLE"), 0.5
        )
        return score * 0.7 + growth * 0.3

    def _sentiment_to_score(self, output: dict[str, Any]) -> float:
        if output.get("_degraded"):
            return 0.5
        sent = {"POSITIVE": 1.0, "NEUTRAL": 0.5, "NEGATIVE": 0.0}.get(
            output.get("sentiment", "NEUTRAL"), 0.5
        )
        heat = float(output.get("heat_score", 50)) / 100.0
        return sent * 0.7 + heat * 0.3

    def _shortterm_to_score(self, output: dict[str, Any]) -> float:
        if output.get("_degraded"):
            return 0.5
        sig = {"BUY": 1.0, "HOLD": 0.5, "SELL": 0.1, "AVOID": 0.0}.get(
            output.get("short_term_signal", "HOLD"), 0.5
        )
        confidence = float(output.get("confidence", 0.5))
        return sig * 0.7 + confidence * 0.3

    @staticmethod
    def _risk_to_score(output: dict[str, Any]) -> float:
        return float(output.get("risk_score", 50)) / 100.0

    def _adjust_weights_for_degraded(self, degraded: list[str]) -> dict[str, float]:
        weights = dict(self.WEIGHTS)
        if not degraded:
            return weights

        lost_weight = sum(weights[name] for name in degraded if name in weights)
        active = [name for name in weights if name not in degraded]
        extra = lost_weight / len(active) if active else 0.0

        for name in degraded:
            weights[name] = 0.0
        for name in active:
            weights[name] += extra
        return weights

    def _build_reason(
        self, action: str, results: dict[str, Any], scores: dict[str, float]
    ) -> str:
        parts: list[str] = []

        trend_out = self._get_output(results.get("trend"))
        if not trend_out.get("_degraded"):
            parts.append(
                f"趋势{trend_out.get('trend', '?')}"
                f"（强度{float(trend_out.get('trend_strength', 0)):.0%}）"
            )

        fund_out = self._get_output(results.get("fundamental"))
        if not fund_out.get("_degraded"):
            parts.append(
                f"基本面评级{fund_out.get('grade', '?')}"
                f"（{fund_out.get('growth_outlook', '?')}）"
            )

        sent_out = self._get_output(results.get("sentiment"))
        if not sent_out.get("_degraded"):
            parts.append(f"市场情绪{sent_out.get('sentiment', '?')}")

        risk_out = self._get_output(results.get("risk"))
        if risk_out.get("issues"):
            parts.append(f"风险提示：{risk_out['issues'][0]}")

        if parts:
            return "；".join(parts)
        return f"综合AI分析，建议{action}"
