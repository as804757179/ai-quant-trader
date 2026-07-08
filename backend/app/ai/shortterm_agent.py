from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from app.ai.base_agent import BaseAgent
from app.core.config import settings


def _deepseek_base_url() -> str:
    url = settings.DEEPSEEK_BASE_URL.rstrip("/")
    if not url.endswith("/v1"):
        return f"{url}/v1"
    return url


class ShortTermAgent(BaseAgent):
    name = "shortterm"
    model = settings.DEEPSEEK_MODEL

    SYSTEM_PROMPT = """你是一名专注A股短线交易的量化分析师。
擅长：超短线形态识别、涨停板逻辑、游资行为分析、日内趋势判断。
时间维度：1-3个交易日。
你只输出JSON格式。"""

    USER_PROMPT_TEMPLATE = """请进行A股短线交易分析（1-3日维度）：

{market_context}

今日分时数据摘要：
- 开盘：{open_price}，最高：{high}，最低：{low}
- 上午走势：{am_trend}
- 下午走势：{pm_trend}
- 尾盘情况：{close_trend}

近3日涨幅：{price_3d_change}%
距离涨停板还有：{to_limit_up}%
距离跌停板还有：{to_limit_down}%

主力封板/砸板情况：{limit_info}

5分钟/15分钟K线动量：
{kline_intraday_summary}

盘口摘要：
{order_book_summary}

请从短线角度分析：
1. 今日K线形态（是否有效突破？假突破？）
2. 是否有涨停板逻辑？（板块联动、题材催化）
3. 短线风险：是否处于高位震荡？前期套牢盘位置？
4. 明日/后日短线机会评估

严格按以下JSON输出：
{{
  "short_term_signal": "BUY",
  "time_horizon": "1-2日",
  "entry_point": 45.50,
  "target_price": 48.00,
  "stop_loss": 43.80,
  "risk_reward_ratio": 2.1,
  "pattern": "缩量回踩MA5反弹",
  "limit_up_probability": 0.25,
  "trap_risk": "低",
  "key_price_levels": {{
    "strong_support": 43.50,
    "weak_support": 44.80,
    "first_target": 47.50,
    "second_target": 49.00
  }},
  "operation_strategy": "操作策略摘要",
  "confidence": 0.68,
  "reason": "短线分析摘要"
}}

注意：
- short_term_signal: BUY/SELL/HOLD/AVOID
- trap_risk: 低/中/高
- risk_reward_ratio必须大于1.5才建议买入"""

    def _calc_limit_distance(
        self, price: float, prev_close: float
    ) -> tuple[str, str]:
        if not price or not prev_close:
            return "N/A", "N/A"
        to_limit_up = round((prev_close * 1.10 - price) / price * 100, 2)
        to_limit_down = round((price - prev_close * 0.90) / price * 100, 2)
        return str(to_limit_up), str(to_limit_down)

    def _format_intraday_klines(self, context: dict[str, Any]) -> str:
        parts: list[str] = []
        for key, label in (("kline_5m", "5分钟"), ("kline_15m", "15分钟")):
            bars = context.get(key) or []
            if not bars:
                continue
            recent = bars[-5:]
            closes = ", ".join(str(b.get("close", "")) for b in recent)
            parts.append(f"{label}近5根收盘：{closes}")
        return "\n".join(parts) if parts else "分钟级K线数据不可用"

    def _format_order_book(self, context: dict[str, Any]) -> str:
        book = context.get("order_book") or {}
        if not book:
            return "盘口数据不可用"
        bid = book.get("bid_volume", "N/A")
        ask = book.get("ask_volume", "N/A")
        spread = book.get("spread_pct", "N/A")
        return f"买盘量={bid}，卖盘量={ask}，买卖价差={spread}%"

    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        kline = context.get("today_kline") or {}
        prev_close = context.get("prev_close") or context.get("price") or 0
        price = context.get("price") or 0
        to_limit_up, to_limit_down = self._calc_limit_distance(
            float(price) if price else 0.0,
            float(prev_close) if prev_close else 0.0,
        )

        prompt = self.USER_PROMPT_TEMPLATE.format(
            market_context=self._build_market_context_str(context),
            open_price=kline.get("open", "N/A"),
            high=kline.get("high", "N/A"),
            low=kline.get("low", "N/A"),
            am_trend=context.get("am_trend", "数据不可用"),
            pm_trend=context.get("pm_trend", "数据不可用"),
            close_trend=context.get("close_trend", "数据不可用"),
            price_3d_change=context.get("price_3d_change", "N/A"),
            to_limit_up=to_limit_up,
            to_limit_down=to_limit_down,
            limit_info=context.get("limit_info", "无涨跌停情况"),
            kline_intraday_summary=self._format_intraday_klines(context),
            order_book_summary=self._format_order_book(context),
        )

        client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=_deepseek_base_url(),
        )
        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.15,
            max_tokens=800,
        )

        usage = response.usage
        self.last_input_tokens = usage.prompt_tokens if usage else 0
        self.last_output_tokens = usage.completion_tokens if usage else 0

        content = response.choices[0].message.content or "{}"
        return self._parse_json_response(content)

    def get_neutral_result(self) -> dict[str, Any]:
        return self._mark_degraded(
            {
                "short_term_signal": "HOLD",
                "confidence": 0.0,
                "reason": "短线分析不可用（服务超时或错误）",
            }
        )