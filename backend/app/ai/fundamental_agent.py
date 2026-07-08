from __future__ import annotations

from typing import Any

import anthropic

from app.ai.base_agent import BaseAgent
from app.core.config import settings
from app.rag.engine import RAGEngine


class FundamentalAgent(BaseAgent):
    name = "fundamental"
    model = settings.ANTHROPIC_MODEL

    SYSTEM_PROMPT = """你是一名专业的A股基本面研究员，擅长财务分析和估值判断。
专注于：盈利质量、成长性、估值水平、行业地位、财务风险。
你只输出JSON格式，分析客观严谨，不夸大不美化。"""

    USER_PROMPT_TEMPLATE = """请对以下A股公司进行基本面分析：

{market_context}

最新财务数据（最近一期报告，报告期：{report_date}，发布日期：{publish_date}）：
- 营业收入：{revenue}（同比：{revenue_yoy}%）
- 净利润：{net_profit}（同比：{profit_yoy}%）
- 毛利率：{gross_margin}%
- 净资产收益率(ROE)：{roe}%
- 资产负债率：{debt_ratio}%
- 经营现金流：{oper_cashflow}
- PE（市盈率）：{pe_ratio}x
- PB（市净率）：{pb_ratio}x
- 每股收益(EPS)：{eps}

近期公告摘要：
{announcements_summary}

RAG检索相关研报摘要：
{research_summary}

请从以下维度分析并评分：
1. 成长性（营收/利润增速、可持续性）
2. 盈利质量（毛利率、现金流质量）
3. 估值水平（PE/PB是否合理，横向对比行业）
4. 财务健康度（资产负债率、偿债能力）
5. 行业地位（龙头/跟随？护城河？）

严格按以下JSON格式输出：
{{
  "overall_score": 72,
  "grade": "B+",
  "growth_score": 75,
  "profitability_score": 80,
  "valuation_score": 65,
  "financial_health_score": 70,
  "industry_position_score": 75,
  "pe_assessment": "合理偏低",
  "pb_assessment": "合理",
  "growth_outlook": "UP",
  "revenue_quality": "优质",
  "key_positives": ["要点1", "要点2"],
  "key_risks": ["风险1", "风险2"],
  "confidence": 0.80,
  "reason": "基本面分析摘要"
}}

注意：
- overall_score: 0-100整数
- grade: A+/A/B+/B/C+/C/D
- growth_outlook: UP/STABLE/DOWN
- confidence: 0.0-1.0"""

    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        stock_code = context.get("code", "")
        rag_ctx = context.get("rag_context") or {}

        if rag_ctx:
            research_summary = rag_ctx.get("research", "")
            announcements_summary = rag_ctx.get("announcements", "")
        else:
            rag = RAGEngine()
            research_summary = await rag.retrieve_research(
                stock_code, top_k=3, stock_code=stock_code
            )
            announcements_summary = await rag.retrieve_announcements(
                stock_code, top_k=5
            )

        report = context.get("financial_report") or {}
        prompt = self.USER_PROMPT_TEMPLATE.format(
            market_context=self._build_market_context_str(context),
            report_date=report.get("report_date", "N/A"),
            publish_date=report.get("publish_date", "N/A"),
            revenue=self._fmt_amount(report.get("revenue")),
            revenue_yoy=report.get("revenue_yoy", "N/A"),
            net_profit=self._fmt_amount(report.get("net_profit")),
            profit_yoy=report.get("profit_yoy", "N/A"),
            gross_margin=report.get("gross_margin", "N/A"),
            roe=report.get("roe", "N/A"),
            debt_ratio=report.get("debt_ratio", "N/A"),
            oper_cashflow=self._fmt_amount(report.get("oper_cashflow")),
            pe_ratio=report.get("pe_ratio", "N/A"),
            pb_ratio=report.get("pb_ratio", "N/A"),
            eps=report.get("eps", "N/A"),
            announcements_summary=announcements_summary or "暂无近期重大公告",
            research_summary=research_summary or "暂无相关研报",
        )

        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model=self.model,
            max_tokens=1000,
            temperature=0.1,
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        self.last_input_tokens = response.usage.input_tokens
        self.last_output_tokens = response.usage.output_tokens

        text_blocks = [block.text for block in response.content if block.type == "text"]
        return self._parse_json_response("".join(text_blocks))

    def get_neutral_result(self) -> dict[str, Any]:
        return self._mark_degraded(
            {
                "overall_score": 50,
                "grade": "C",
                "growth_outlook": "STABLE",
                "confidence": 0.0,
                "reason": "基本面分析不可用（服务超时或错误）",
            }
        )