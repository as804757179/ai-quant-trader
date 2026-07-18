from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.ai.aggregator import SignalAggregator
from app.ai.schemas import AgentResult, AgentStatus


def _healthy_results():
    return {
        "trend": {"trend": "UP", "trend_strength": 0.9, "confidence": 0.9},
        "fundamental": {"overall_score": 90, "growth_outlook": "UP"},
        "sentiment": {"sentiment": "POSITIVE", "heat_score": 90},
        "shortterm": {"short_term_signal": "BUY", "confidence": 0.9},
        "risk": {"risk_score": 90, "risk_level": "LOW", "pass": True},
    }


class AiFailClosedTests(unittest.TestCase):
    def test_degraded_required_agent_forces_hold_without_weight_redistribution(self):
        results = _healthy_results()
        results["fundamental"] = {"_degraded": True}
        signal = SignalAggregator().aggregate(results, "600000", 10.0)
        self.assertEqual(signal["action"], "HOLD")
        self.assertEqual(signal["confidence"], 0.0)
        self.assertIn("fundamental", signal["degraded_agents"])

    def test_missing_risk_agent_forces_hold(self):
        results = _healthy_results()
        del results["risk"]
        signal = SignalAggregator().aggregate(results, "600000", 10.0)
        self.assertEqual(signal["action"], "HOLD")
        self.assertIn("risk", signal["degraded_agents"])

    def test_failed_agent_result_without_degraded_marker_forces_hold(self):
        results = _healthy_results()
        results["trend"] = AgentResult(
            agent_name="trend",
            model="test",
            output={"trend": "UP", "trend_strength": 1.0, "confidence": 1.0},
            status=AgentStatus.ERROR,
            latency_ms=1,
        )
        signal = SignalAggregator().aggregate(results, "600000", 10.0)
        self.assertEqual(signal["action"], "HOLD")
        self.assertIn("trend", signal["degraded_agents"])


if __name__ == "__main__":
    unittest.main()
