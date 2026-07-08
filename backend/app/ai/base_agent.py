from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod
from typing import Any

import structlog

from app.ai.schemas import AgentResult, AgentStatus
from app.core.config import settings

logger = structlog.get_logger(__name__)


class BaseAgent(ABC):
    """
    AI Agent 抽象基类。

    职责：
    - 定义统一的 analyze / get_neutral_result 接口
    - 提供 JSON 解析与市场上下文格式化工具
    - 通过 run_safe() 封装超时控制、降级与结构化日志
    """

    name: str = ""
    model: str = ""
    timeout_seconds: float = 30.0

    last_input_tokens: int = 0
    last_output_tokens: int = 0

    def __init__(self) -> None:
        self._configure_timeout()

    def _configure_timeout(self) -> None:
        timeout_map = {
            "trend": settings.OPENAI_TIMEOUT,
            "fundamental": settings.ANTHROPIC_TIMEOUT,
            "sentiment": settings.QWEN_TIMEOUT,
            "shortterm": settings.DEEPSEEK_TIMEOUT,
        }
        if self.name in timeout_map:
            self.timeout_seconds = float(timeout_map[self.name])

    @abstractmethod
    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """执行分析，返回标准格式 dict。"""

    @abstractmethod
    def get_neutral_result(self) -> dict[str, Any]:
        """降级时返回的中性结果（不影响最终信号方向）。"""

    async def run_safe(self, context: dict[str, Any]) -> AgentResult:
        """
        带超时、降级与日志的安全执行入口。
        Orchestrator 应优先调用此方法而非直接调用 analyze()。
        """
        stock_code = context.get("code", "unknown")
        start = time.perf_counter()
        logger.info(
            "agent_start",
            agent=self.name,
            model=self.model,
            stock_code=stock_code,
            timeout_seconds=self.timeout_seconds,
        )

        try:
            output = await asyncio.wait_for(
                self.analyze(context),
                timeout=self.timeout_seconds,
            )
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "agent_success",
                agent=self.name,
                stock_code=stock_code,
                latency_ms=latency_ms,
                input_tokens=self.last_input_tokens,
                output_tokens=self.last_output_tokens,
            )
            return AgentResult(
                agent_name=self.name,
                model=self.model,
                output=output,
                status=AgentStatus.SUCCESS,
                latency_ms=latency_ms,
                input_tokens=self.last_input_tokens,
                output_tokens=self.last_output_tokens,
            )
        except asyncio.TimeoutError:
            latency_ms = int(self.timeout_seconds * 1000)
            error_msg = f"Timeout after {self.timeout_seconds}s"
            logger.warning(
                "agent_timeout",
                agent=self.name,
                stock_code=stock_code,
                latency_ms=latency_ms,
                error=error_msg,
            )
            return AgentResult(
                agent_name=self.name,
                model=self.model,
                output=self.get_neutral_result(),
                status=AgentStatus.TIMEOUT,
                latency_ms=latency_ms,
                input_tokens=0,
                output_tokens=0,
                error_msg=error_msg,
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.error(
                "agent_error",
                agent=self.name,
                stock_code=stock_code,
                latency_ms=latency_ms,
                error=str(exc),
                exc_info=True,
            )
            return AgentResult(
                agent_name=self.name,
                model=self.model,
                output=self.get_neutral_result(),
                status=AgentStatus.ERROR,
                latency_ms=latency_ms,
                input_tokens=0,
                output_tokens=0,
                error_msg=str(exc),
            )

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        """安全解析 AI 返回的 JSON，自动去除 markdown 代码块。"""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            if len(parts) >= 2:
                cleaned = parts[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
        cleaned = cleaned.strip("`").strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Agent {self.name} returned invalid JSON: {exc}\nRaw: {cleaned[:200]}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"Agent {self.name} JSON root must be an object")
        return parsed

    def _build_market_context_str(self, context: dict[str, Any]) -> str:
        """将 market context 格式化为提示词友好的字符串。"""
        volume = context.get("volume")
        volume_str = f"{volume:,}" if isinstance(volume, (int, float)) else "N/A"
        return f"""
股票代码：{context.get('code')}  股票名称：{context.get('name')}
所属行业：{context.get('sector')}  所属板块：{context.get('board')}
当前价格：{context.get('price')}  市值：{context.get('market_cap_str', 'N/A')}

K线数据（近20日收盘价）：
{context.get('close_prices_str', 'N/A')}

技术指标：
- MA5={context.get('ma5', 'N/A')}  MA20={context.get('ma20', 'N/A')}  MA60={context.get('ma60', 'N/A')}
- MACD={context.get('macd', 'N/A')}  信号线={context.get('macd_signal', 'N/A')}
- RSI(14)={context.get('rsi14', 'N/A')}
- 布林带：上={context.get('bb_upper', 'N/A')}  中={context.get('bb_mid', 'N/A')}  下={context.get('bb_lower', 'N/A')}
- 成交量：{volume_str}  量比={context.get('volume_ratio', 'N/A')}
"""

    @staticmethod
    def _fmt_amount(value: Any) -> str:
        if value is None:
            return "N/A"
        try:
            num = float(value)
        except (TypeError, ValueError):
            return str(value)
        if abs(num) >= 1e8:
            return f"{num / 1e8:.2f}亿"
        return f"{num / 1e4:.2f}万"

    def _mark_degraded(self, output: dict[str, Any]) -> dict[str, Any]:
        """为降级输出打上统一标记。"""
        output["_degraded"] = True
        return output