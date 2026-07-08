from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from app.ai.base_agent import BaseAgent
from app.core.config import settings


def _qwen_base_url() -> str:
    url = settings.QWEN_BASE_URL.rstrip("/")
    if "dashscope" in url and "compatible-mode" not in url:
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if not url.endswith("/v1"):
        return f"{url}/v1"
    return url


class SentimentAgent(BaseAgent):
    name = "sentiment"
    model = settings.QWEN_MODEL

    SYSTEM_PROMPT = """你是一名A股市场情绪分析专家，专注于：
- 新闻舆论情绪分析
- 资金动向解读（北向、主力、龙虎榜）
- 投资者情绪量化
你只输出JSON，分析要结合A股特有的市场生态（游资、北向、涨停板效应等）。"""

    USER_PROMPT_TEMPLATE = """请分析以下A股的市场情绪状态：

{market_context}

近7日相关新闻（按时间倒序）：
{news_list}

资金流向（今日）：
- 主力净流入：{main_net_in}
- 超大单净流入：{super_large_in}
- 北向资金今日净买入：{north_today}
- 北向资金5日净买入：{north_5d}

龙虎榜情况：
{dragon_tiger_info}

市场热度指标：
- 今日换手率：{turnover_rate}%（近30日均值：{avg_turnover_30d}%）
- 量比：{volume_ratio}

请分析：
1. 新闻舆论整体倾向（利好/利空/中性）
2. 机构资金（北向）的态度
3. 游资/主力动向（龙虎榜分析）
4. 散户情绪（换手率、量比判断热度）
5. 综合情绪打分

严格按以下JSON格式输出：
{{
  "sentiment": "POSITIVE",
  "sentiment_score": 72,
  "news_sentiment": "POSITIVE",
  "news_key_points": ["要点1", "要点2"],
  "institution_attitude": "净买入",
  "north_flow_assessment": "持续流入",
  "retail_emotion": "乐观",
  "hot_money_signal": "游资介入迹象",
  "heat_score": 78,
  "catalysts": ["催化1"],
  "negative_factors": ["风险1"],
  "confidence": 0.75,
  "reason": "情绪分析摘要"
}}

注意：
- sentiment: POSITIVE/NEUTRAL/NEGATIVE
- institution_attitude: 净买入/中性/净卖出
- retail_emotion: 乐观/中性/悲观
- heat_score: 0-100，综合热度分"""

    def _format_news(self, news: list[dict[str, Any]]) -> str:
        if not news:
            return "暂无近期新闻"
        lines = []
        for item in news[:10]:
            publish_time = str(item.get("publish_time", ""))[:10]
            title = item.get("title", "")
            lines.append(f"[{publish_time}] {title}")
        return "\n".join(lines)

    def _format_dragon_tiger(self, entries: list[dict[str, Any]]) -> str:
        if not entries:
            return "本股近期未上龙虎榜"
        return "\n".join(
            f"- {d.get('trader', '未知')}：{d.get('side', '')} {d.get('amount', '')}"
            for d in entries
        )

    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        fund = context.get("fund_flow") or {}
        north = context.get("north_flow") or {}

        prompt = self.USER_PROMPT_TEMPLATE.format(
            market_context=self._build_market_context_str(context),
            news_list=self._format_news(context.get("news") or []),
            main_net_in=self._fmt_amount(fund.get("main_net_in")),
            super_large_in=self._fmt_amount(fund.get("super_large_in")),
            north_today=self._fmt_amount(north.get("today")),
            north_5d=self._fmt_amount(north.get("five_day")),
            dragon_tiger_info=self._format_dragon_tiger(context.get("dragon_tiger") or []),
            turnover_rate=context.get("turnover_rate", "N/A"),
            avg_turnover_30d=context.get("avg_turnover_30d", "N/A"),
            volume_ratio=context.get("volume_ratio", "N/A"),
        )

        client = AsyncOpenAI(
            api_key=settings.QWEN_API_KEY,
            base_url=_qwen_base_url(),
        )
        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
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
                "sentiment": "NEUTRAL",
                "sentiment_score": 50,
                "heat_score": 50,
                "confidence": 0.0,
                "reason": "情绪分析不可用（服务超时或错误）",
            }
        )