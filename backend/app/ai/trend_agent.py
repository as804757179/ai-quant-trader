from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from app.ai.base_agent import BaseAgent
from app.core.config import settings


class TrendAgent(BaseAgent):
    name = "trend"
    model = settings.OPENAI_MODEL

    SYSTEM_PROMPT = """你是一名专业的A股技术分析师，擅长趋势判断和形态识别。
你的分析必须基于提供的数据，不得捏造数据。
你只输出JSON格式，不输出任何其他内容。"""

    USER_PROMPT_TEMPLATE = """请分析以下A股的技术趋势，判断未来3-10个交易日的**中短期趋势方向**（非超短线）。

{market_context}

补充指标：
- 换手率：{turnover_rate}%
- 近5日涨跌幅：{price_changes_5d}

**输入数据（中短周期专用）**：
- 日线/周线K线（近60日）
- 主要均线系统（MA5/10/20/60/120排列）
- MACD (12,26,9) 日线状态 + 柱状图趋势
- RSI (14) 日线 + 周线
- 成交量 + 换手率趋势（非单日）
- 关键支撑/压力位（前高/前低/整数关口）

**严禁分析**：5分钟/15分钟超短线形态、盘口买卖盘、分钟级 momentum burst（这些交给ShortTermAgent）。

分析要点（仅中短周期）：
1. 均线多空排列与趋势强度
2. MACD日线金叉/死叉 + 柱状图持续性
3. RSI日/周线背离或超买超卖
4. 量价中长期配合度
5. 关键位置突破/跌破的有效性

严格按以下JSON格式输出，不要任何其他文字：
{{
  "trend": "UP",
  "trend_strength": 0.75,
  "time_horizon": "3-10交易日（中短期）",
  "support": 45.20,
  "resistance": 50.80,
  "ma_alignment": "多头排列",
  "macd_status": "金叉形成且柱持续放大",
  "rsi_status": "正常区间，无周线背离",
  "volume_quality": "中长期量价配合良好",
  "key_signals": ["MA20上穿MA60", "MACD日线金叉持续", "周线RSI健康"],
  "risk_factors": ["接近前高压力位50.80", "需确认放量突破"],
  "confidence": 0.72,
  "reason": "趋势分析摘要（200字以内）"
}}

注意：
- trend只能是: UP / DOWN / SIDEWAYS
- trend_strength: 0.0-1.0
- confidence: 0.0-1.0
- reason必须在200字以内"""

    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        prompt = self.USER_PROMPT_TEMPLATE.format(
            market_context=self._build_market_context_str(context),
            turnover_rate=context.get("turnover_rate", "N/A"),
            price_changes_5d=context.get("price_changes_5d", "N/A"),
        )

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=800,
            response_format={"type": "json_object"},
        )

        usage = response.usage
        self.last_input_tokens = usage.prompt_tokens if usage else 0
        self.last_output_tokens = usage.completion_tokens if usage else 0

        content = response.choices[0].message.content or "{}"
        return self._parse_json_response(content)

    def get_neutral_result(self) -> dict[str, Any]:
        return self._mark_degraded(
            {
                "trend": "SIDEWAYS",
                "trend_strength": 0.5,
                "support": None,
                "resistance": None,
                "confidence": 0.0,
                "reason": "趋势分析不可用（服务超时或错误）",
            }
        )