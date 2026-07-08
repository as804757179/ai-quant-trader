# 15 & 16 — AI架构与Agent完整设计

---

## Part 1: AI层架构

### 1.1 设计原则

```
1. 故障隔离：单个Agent失败不阻断流程，降级返回中性结果
2. 并发执行：4个分析Agent并发运行，缩短总耗时
3. 可追溯：每次AI调用完整记录输入/输出/耗时/Token消耗
4. 成本控制：按Agent选择合适模型（不是所有Agent都用最贵的模型）
5. 置信度校准：原始AI置信度经过历史校准，防止系统性高估
```

### 1.2 Agent调用流程

```python
# backend/app/ai/orchestrator.py

import asyncio
from typing import Optional
from dataclasses import dataclass

@dataclass
class AgentResult:
    agent_name: str
    model: str
    output: dict
    status: str          # success / timeout / error / degraded
    latency_ms: int
    input_tokens: int
    output_tokens: int
    error_msg: Optional[str] = None

class AgentOrchestrator:
    """
    多Agent并发调度器
    """
    AGENT_TIMEOUT = 30  # 每个Agent最大等待时间（秒）
    ORCHESTRATOR_TIMEOUT = 45  # 整体超时（秒）

    def __init__(self):
        self.trend_agent = TrendAgent()
        self.fundamental_agent = FundamentalAgent()
        self.sentiment_agent = SentimentAgent()
        self.shortterm_agent = ShortTermAgent()
        self.risk_agent = RiskAgent()
        self.portfolio_agent = PortfolioAgent()
        self.aggregator = SignalAggregator()

    async def analyze(self, stock_code: str, context: dict) -> dict:
        """
        完整分析流程
        Step 1: 并发运行4个分析Agent
        Step 2: 风控Agent评估
        Step 3: 聚合信号
        Step 4: 仓位建议
        """
        # Step 1: 并发分析（4个Agent同时跑）
        analysis_tasks = [
            self._run_agent_safe(self.trend_agent, context),
            self._run_agent_safe(self.fundamental_agent, context),
            self._run_agent_safe(self.sentiment_agent, context),
            self._run_agent_safe(self.shortterm_agent, context),
        ]

        agent_results = await asyncio.gather(*analysis_tasks)

        trend_r, fundamental_r, sentiment_r, shortterm_r = agent_results

        # Step 2: 风控评估（同步，不调用外部LLM）
        risk_r = self.risk_agent.evaluate(context, agent_results)

        # Step 3: 信号聚合
        signal = self.aggregator.aggregate({
            'trend': trend_r,
            'fundamental': fundamental_r,
            'sentiment': sentiment_r,
            'shortterm': shortterm_r,
            'risk': risk_r,
        }, stock_code=stock_code, current_price=context['price'])

        # Step 4: 仓位建议（只在BUY信号时计算）
        if signal['action'] == 'BUY':
            portfolio_advice = await self._run_agent_safe(
                self.portfolio_agent,
                {**context, 'signal': signal}
            )
            signal['position_advice'] = portfolio_advice.output

        # 记录完整日志
        await self._save_agent_logs(signal['id'], agent_results + [risk_r])

        return signal

    async def _run_agent_safe(self, agent, context: dict) -> AgentResult:
        """带超时和降级的Agent执行"""
        import time
        start = time.time()
        try:
            result = await asyncio.wait_for(
                agent.analyze(context),
                timeout=self.AGENT_TIMEOUT
            )
            return AgentResult(
                agent_name=agent.name,
                model=agent.model,
                output=result,
                status='success',
                latency_ms=int((time.time() - start) * 1000),
                input_tokens=agent.last_input_tokens,
                output_tokens=agent.last_output_tokens,
            )
        except asyncio.TimeoutError:
            return AgentResult(
                agent_name=agent.name, model=agent.model,
                output=agent.get_neutral_result(),
                status='timeout', latency_ms=self.AGENT_TIMEOUT * 1000,
                input_tokens=0, output_tokens=0,
                error_msg=f"Timeout after {self.AGENT_TIMEOUT}s"
            )
        except Exception as e:
            return AgentResult(
                agent_name=agent.name, model=agent.model,
                output=agent.get_neutral_result(),
                status='error', latency_ms=int((time.time() - start) * 1000),
                input_tokens=0, output_tokens=0,
                error_msg=str(e)
            )
```

---

## Part 2: 6个Agent完整设计

### 2.1 BaseAgent（基类）

```python
# backend/app/ai/agents/base_agent.py

from abc import ABC, abstractmethod
from typing import Any
import json

class BaseAgent(ABC):
    name: str = ""
    model: str = ""
    last_input_tokens: int = 0
    last_output_tokens: int = 0

    @abstractmethod
    async def analyze(self, context: dict) -> dict:
        """执行分析，返回标准格式dict"""
        pass

    @abstractmethod
    def get_neutral_result(self) -> dict:
        """降级时返回的中性结果（不影响最终信号方向）"""
        pass

    def _parse_json_response(self, text: str) -> dict:
        """安全解析AI返回的JSON，自动去除markdown代码块"""
        text = text.strip()
        if text.startswith('```'):
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        text = text.strip('`').strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Agent {self.name} returned invalid JSON: {e}\nRaw: {text[:200]}")

    def _build_market_context_str(self, context: dict) -> str:
        """将market context格式化为提示词友好的字符串"""
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
- 成交量：{context.get('volume_str', 'N/A')}  量比={context.get('volume_ratio', 'N/A')}
"""
```

### 2.2 TrendAgent（GPT - 趋势判断）

```python
# backend/app/ai/agents/trend_agent.py

import openai
from .base_agent import BaseAgent

class TrendAgent(BaseAgent):
    name = "trend"
    model = "gpt-4o"

    SYSTEM_PROMPT = """你是一名专业的A股技术分析师，擅长趋势判断和形态识别。
你的分析必须基于提供的数据，不得捏造数据。
你只输出JSON格式，不输出任何其他内容。"""

    USER_PROMPT_TEMPLATE = """请分析以下A股的技术趋势，判断未来3-10个交易日的**中短期趋势方向**（非超短线）。

{market_context}

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
  "reason": "日线价格站上MA20且MA20上穿MA60形成多头排列，MACD日线金叉且柱状图持续放大3日，成交量中长期趋势配合。趋势向上信号明确。主要风险是接近前高压力位，需关注有效突破确认。"
}}

注意：
- trend只能是: UP / DOWN / SIDEWAYS
- time_horizon 明确为中短期（3-10交易日）
- 严禁输出超短线内容（5min形态、盘口等）
- trend_strength: 0.0-1.0，代表趋势强度
- confidence: 0.0-1.0，代表你对此判断的把握程度
- reason必须在200字以内，简洁有力"""

    async def analyze(self, context: dict) -> dict:
        prompt = self.USER_PROMPT_TEMPLATE.format(
            market_context=self._build_market_context_str(context),
            turnover_rate=context.get('turnover_rate', 'N/A'),
            price_changes_5d=context.get('price_changes_5d', 'N/A'),
        )

        client = openai.AsyncOpenAI()
        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,     # 低temperature保证稳定性
            max_tokens=800,
            response_format={"type": "json_object"},  # 强制JSON输出
        )

        self.last_input_tokens = response.usage.prompt_tokens
        self.last_output_tokens = response.usage.completion_tokens

        return self._parse_json_response(response.choices[0].message.content)

    def get_neutral_result(self) -> dict:
        return {
            "trend": "SIDEWAYS", "trend_strength": 0.5,
            "support": None, "resistance": None,
            "confidence": 0.0,
            "reason": "趋势分析不可用（服务超时或错误）",
            "_degraded": True
        }
```

### 2.3 FundamentalAgent（Claude - 基本面分析）

```python
# backend/app/ai/agents/fundamental_agent.py

import anthropic
from .base_agent import BaseAgent

class FundamentalAgent(BaseAgent):
    name = "fundamental"
    model = "claude-3-5-sonnet-20241022"

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
  "key_positives": [
    "营收保持25%以上高增长",
    "毛利率稳定在45%以上，行业领先",
    "经营现金流充裕，净利润含金量高"
  ],
  "key_risks": [
    "资产负债率较高（65%），需关注偿债压力",
    "PE相对行业均值偏高，存在估值回调风险"
  ],
  "confidence": 0.80,
  "reason": "公司基本面扎实，营收和利润保持高增长，盈利质量较高，现金流健康。估值在成长股中属于合理区间。主要风险是负债率偏高和行业竞争加剧。综合评级B+。"
}}

注意：
- overall_score: 0-100整数
- grade: A+/A/B+/B/C+/C/D
- growth_outlook: UP/STABLE/DOWN
- confidence: 0.0-1.0"""

    async def analyze(self, context: dict) -> dict:
        # 从RAG获取研报和公告摘要
        from app.rag.engine import RAGEngine
        rag = RAGEngine()
        research_summary = await rag.retrieve_research(context['code'], top_k=3)
        announcements_summary = await rag.retrieve_announcements(context['code'], top_k=5)

        report = context.get('financial_report', {})
        prompt = self.USER_PROMPT_TEMPLATE.format(
            market_context=self._build_market_context_str(context),
            report_date=report.get('report_date', 'N/A'),
            publish_date=report.get('publish_date', 'N/A'),
            revenue=self._fmt_amount(report.get('revenue')),
            revenue_yoy=report.get('revenue_yoy', 'N/A'),
            net_profit=self._fmt_amount(report.get('net_profit')),
            profit_yoy=report.get('profit_yoy', 'N/A'),
            gross_margin=report.get('gross_margin', 'N/A'),
            roe=report.get('roe', 'N/A'),
            debt_ratio=report.get('debt_ratio', 'N/A'),
            oper_cashflow=self._fmt_amount(report.get('oper_cashflow')),
            pe_ratio=report.get('pe_ratio', 'N/A'),
            pb_ratio=report.get('pb_ratio', 'N/A'),
            eps=report.get('eps', 'N/A'),
            announcements_summary=announcements_summary or "暂无近期重大公告",
            research_summary=research_summary or "暂无相关研报",
        )

        client = anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=self.model,
            max_tokens=1000,
            temperature=0.1,
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )

        self.last_input_tokens = response.usage.input_tokens
        self.last_output_tokens = response.usage.output_tokens

        return self._parse_json_response(response.content[0].text)

    def _fmt_amount(self, value) -> str:
        if value is None:
            return "N/A"
        if abs(value) >= 1e8:
            return f"{value/1e8:.2f}亿"
        return f"{value/1e4:.2f}万"

    def get_neutral_result(self) -> dict:
        return {
            "overall_score": 50, "grade": "C",
            "growth_outlook": "STABLE",
            "confidence": 0.0,
            "reason": "基本面分析不可用（服务超时或错误）",
            "_degraded": True
        }
```

### 2.4 SentimentAgent（Qwen - 情绪分析）

```python
# backend/app/ai/agents/sentiment_agent.py

from openai import AsyncOpenAI  # Qwen兼容OpenAI接口
from .base_agent import BaseAgent
import os

class SentimentAgent(BaseAgent):
    name = "sentiment"
    model = "qwen-plus"   # 中文情绪分析用Qwen效果更好

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
  "news_key_points": [
    "公司获得国家重点专项支持（利好）",
    "行业监管趋严（轻微利空）"
  ],
  "institution_attitude": "净买入",
  "north_flow_assessment": "持续流入，5日累计买入超2亿",
  "retail_emotion": "乐观",
  "hot_money_signal": "游资介入迹象明显（龙虎榜上榜）",
  "heat_score": 78,
  "catalysts": ["国家政策支持", "机构持续买入", "行业景气度提升"],
  "negative_factors": ["市场整体情绪偏弱", "获利盘压力"],
  "confidence": 0.75,
  "reason": "新闻面整体偏正面，公司获得政策支持催化，北向资金5日持续净买入。游资有介入迹象，散户热度适中（换手率略高于均值）。综合情绪偏积极，但需注意市场整体偏弱的背景风险。"
}}

注意：
- sentiment: POSITIVE/NEUTRAL/NEGATIVE
- institution_attitude: 净买入/中性/净卖出
- retail_emotion: 乐观/中性/悲观
- heat_score: 0-100，综合热度分"""

    async def analyze(self, context: dict) -> dict:
        # 格式化新闻列表
        news = context.get('news', [])
        news_str = "\n".join([
            f"[{n['publish_time'][:10]}] {n['title']}"
            for n in news[:10]
        ]) or "暂无近期新闻"

        # 龙虎榜
        dt = context.get('dragon_tiger', [])
        dt_str = "\n".join([
            f"- {d['trader']}：{d['side']} {d['amount']}"
            for d in dt
        ]) if dt else "本股近期未上龙虎榜"

        fund = context.get('fund_flow', {})
        north = context.get('north_flow', {})

        prompt = self.USER_PROMPT_TEMPLATE.format(
            market_context=self._build_market_context_str(context),
            news_list=news_str,
            main_net_in=self._fmt_amount(fund.get('main_net_in')),
            super_large_in=self._fmt_amount(fund.get('super_large_in')),
            north_today=self._fmt_amount(north.get('today')),
            north_5d=self._fmt_amount(north.get('five_day')),
            dragon_tiger_info=dt_str,
            turnover_rate=context.get('turnover_rate', 'N/A'),
            avg_turnover_30d=context.get('avg_turnover_30d', 'N/A'),
            volume_ratio=context.get('volume_ratio', 'N/A'),
        )

        client = AsyncOpenAI(
            api_key=os.getenv('QWEN_API_KEY'),
            base_url=os.getenv('QWEN_BASE_URL'),
        )
        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=800,
        )

        self.last_input_tokens = response.usage.prompt_tokens
        self.last_output_tokens = response.usage.completion_tokens
        return self._parse_json_response(response.choices[0].message.content)

    def _fmt_amount(self, value) -> str:
        if value is None: return "N/A"
        if abs(value) >= 1e8: return f"{value/1e8:.2f}亿"
        return f"{value/1e4:.2f}万"

    def get_neutral_result(self) -> dict:
        return {
            "sentiment": "NEUTRAL", "sentiment_score": 50,
            "heat_score": 50, "confidence": 0.0,
            "reason": "情绪分析不可用（服务超时或错误）",
            "_degraded": True
        }
```

### 2.5 ShortTermAgent（DeepSeek - 短线交易）

```python
# backend/app/ai/agents/shortterm_agent.py

from openai import AsyncOpenAI
from .base_agent import BaseAgent
import os

class ShortTermAgent(BaseAgent):
    name = "shortterm"
    model = "deepseek-chat"   # DeepSeek性价比高，适合短线分析

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
  "operation_strategy": "可在45.00-45.80区间轻仓买入，止损43.80，目标48.00",
  "confidence": 0.68,
  "reason": "今日缩量回踩MA5形成支撑，分时图下午有明显护盘迹象，明日有望企稳反弹。止损设在前低43.80，风险收益比2.1，可轻仓参与。"
}}

注意：
- short_term_signal: BUY/SELL/HOLD/AVOID
- trap_risk: 低/中/高
- risk_reward_ratio必须大于1.5才建议买入"""

    async def analyze(self, context: dict) -> dict:
        kline = context.get('today_kline', {})
        prev_close = context.get('prev_close', context.get('price', 0))
        price = context.get('price', 0)

        to_limit_up = round((prev_close * 1.10 - price) / price * 100, 2) if price else 'N/A'
        to_limit_down = round((price - prev_close * 0.90) / price * 100, 2) if price else 'N/A'

        prompt = self.USER_PROMPT_TEMPLATE.format(
            market_context=self._build_market_context_str(context),
            open_price=kline.get('open', 'N/A'),
            high=kline.get('high', 'N/A'),
            low=kline.get('low', 'N/A'),
            am_trend=context.get('am_trend', '数据不可用'),
            pm_trend=context.get('pm_trend', '数据不可用'),
            close_trend=context.get('close_trend', '数据不可用'),
            price_3d_change=context.get('price_3d_change', 'N/A'),
            to_limit_up=to_limit_up,
            to_limit_down=to_limit_down,
            limit_info=context.get('limit_info', '无涨跌停情况'),
        )

        client = AsyncOpenAI(
            api_key=os.getenv('DEEPSEEK_API_KEY'),
            base_url=os.getenv('DEEPSEEK_BASE_URL'),
        )
        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.15,
            max_tokens=800,
        )

        self.last_input_tokens = response.usage.prompt_tokens
        self.last_output_tokens = response.usage.completion_tokens
        return self._parse_json_response(response.choices[0].message.content)

    def get_neutral_result(self) -> dict:
        return {
            "short_term_signal": "HOLD", "confidence": 0.0,
            "reason": "短线分析不可用（服务超时或错误）",
            "_degraded": True
        }
```

### 2.6 RiskAgent（内部风控，不调用外部LLM）

```python
# backend/app/ai/agents/risk_agent.py

class RiskAgent:
    """
    风控评估Agent
    注意：此Agent不调用外部LLM，只做规则计算
    目的：评估当前持仓和市场风险，影响信号最终置信度
    """
    name = "risk"

    def evaluate(self, context: dict, agent_results: list) -> dict:
        """
        综合评估交易风险
        返回风险评估结果，影响信号聚合
        """
        issues = []
        score = 100  # 从100分开始扣分

        # 1. 高波动性惩罚
        rsi = context.get('rsi14', 50)
        if rsi > 75:
            score -= 20
            issues.append(f"RSI={rsi:.1f}，股票处于超买区间，追高风险大")
        elif rsi < 25:
            score -= 10
            issues.append(f"RSI={rsi:.1f}，超卖区间，但下跌趋势中可能继续下跌")

        # 2. 连续涨幅过大
        price_5d_change = context.get('price_5d_change', 0)
        if price_5d_change > 20:
            score -= 25
            issues.append(f"5日涨幅{price_5d_change:.1f}%，短期涨幅过大，回调风险高")

        # 3. 量价背离
        volume_ratio = context.get('volume_ratio', 1.0)
        trend_result = next((r for r in agent_results if hasattr(r, 'agent_name') and r.agent_name == 'trend'), None)
        if trend_result and trend_result.output.get('trend') == 'UP' and volume_ratio < 0.7:
            score -= 15
            issues.append("价格上涨但成交量萎缩，量价背离，趋势可信度低")

        # 4. 高位ST风险
        if context.get('is_st', False):
            score = min(score, 20)
            issues.append("ST股票，风险极高，不建议操作")

        # 5. 距涨停过近（追高风险）
        price = context.get('price', 0)
        prev_close = context.get('prev_close', price)
        if prev_close > 0:
            pct_to_limit = (prev_close * 1.10 - price) / price * 100
            if pct_to_limit < 2 and pct_to_limit > 0:
                score -= 20
                issues.append(f"距涨停板仅{pct_to_limit:.1f}%，追板风险极高")

        # 6. Agent分歧度评估
        agent_confidences = [
            r.output.get('confidence', 0.5)
            for r in agent_results
            if r.status == 'success' and not r.output.get('_degraded')
        ]
        if len(agent_confidences) < 2:
            score -= 10
            issues.append("有效Agent不足，分析结果可信度降低")

        # 7. 流动性检查
        daily_amount = context.get('daily_amount', 0)
        if daily_amount < 3000_0000:  # 日成交额低于3000万
            score -= 15
            issues.append(f"日成交额仅{daily_amount/1e4:.0f}万，流动性不足，大单进出困难")

        risk_level = (
            'LOW' if score >= 80
            else 'MEDIUM' if score >= 60
            else 'HIGH' if score >= 40
            else 'EXTREME'
        )

        return {
            "risk_score": max(0, score),
            "risk_level": risk_level,
            "issues": issues,
            "pass": risk_level not in ('HIGH', 'EXTREME'),
            "confidence": 0.9,  # 规则引擎，置信度固定高
            "reason": f"风控评分{score}分，风险等级{risk_level}。" + (
                "发现问题：" + "；".join(issues) if issues else "无明显风险因素。"
            )
        }

    def get_neutral_result(self) -> dict:
        return {
            "risk_score": 50, "risk_level": "MEDIUM",
            "pass": True, "issues": [],
            "confidence": 0.5, "reason": "风控评估使用默认值"
        }
```

### 2.7 信号聚合器（SignalAggregator）

```python
# backend/app/ai/signal.py

import uuid
from datetime import datetime, timedelta
from typing import Optional

class SignalAggregator:
    """
    加权聚合各Agent结果，生成最终交易信号

    权重设计：
    - 趋势(30%) + 基本面(25%) + 情绪(20%) + 短线(15%) + 风控(10%)
    - 风控为EXTREME时，直接屏蔽信号
    """

    WEIGHTS = {
        'trend': 0.30,
        'fundamental': 0.25,
        'sentiment': 0.20,
        'shortterm': 0.15,
        'risk': 0.10,
    }

    BUY_THRESHOLD = 0.68      # 综合得分超过此值发出BUY
    SELL_THRESHOLD = 0.32     # 综合得分低于此值发出SELL

    def aggregate(self, results: dict, stock_code: str, current_price: float) -> dict:
        # 提取各维度得分（映射到0-1）
        scores = {
            'trend':       self._trend_to_score(results['trend'].output),
            'fundamental': self._fundamental_to_score(results['fundamental'].output),
            'sentiment':   self._sentiment_to_score(results['sentiment'].output),
            'shortterm':   self._shortterm_to_score(results['shortterm'].output),
            'risk':        self._risk_to_score(results['risk']),
        }

        # 风控极端风险直接屏蔽
        if results['risk'].get('risk_level') == 'EXTREME':
            return self._build_signal(
                stock_code, 'HOLD', 0.1, 'EXTREME', current_price,
                "风控评级EXTREME，屏蔽所有交易信号", results, scores
            )

        # 加权计算综合得分
        degraded_agents = [
            name for name, r in results.items()
            if isinstance(r, dict) and r.get('_degraded')
            or hasattr(r, 'output') and r.output.get('_degraded')
        ]

        # 降级Agent权重转移到其他正常Agent
        effective_weights = self._adjust_weights_for_degraded(degraded_agents)

        composite_score = sum(
            scores[name] * effective_weights[name]
            for name in scores
        )

        # 确定信号方向
        if composite_score >= self.BUY_THRESHOLD:
            action = 'BUY'
        elif composite_score <= self.SELL_THRESHOLD:
            action = 'SELL'
        else:
            action = 'HOLD'

        # 构建reason摘要
        reason = self._build_reason(action, results, scores)

        # 风险等级
        risk_level = results['risk'].get('risk_level', 'MEDIUM')

        return self._build_signal(
            stock_code, action, composite_score, risk_level,
            current_price, reason, results, scores
        )

    def _build_signal(self, stock_code, action, confidence, risk_level,
                      price, reason, results, scores) -> dict:
        return {
            'id': str(uuid.uuid4()),
            'stock_code': stock_code,
            'action': action,
            'confidence': round(confidence, 4),
            'risk_level': risk_level,
            'price_at': price,
            'reason': reason,
            'scores': scores,
            'agent_votes': {
                name: r.output if hasattr(r, 'output') else r
                for name, r in results.items()
            },
            'signal_time': datetime.utcnow().isoformat(),
            'valid_until': (datetime.utcnow() + timedelta(hours=24)).isoformat(),
        }

    def _trend_to_score(self, output: dict) -> float:
        if output.get('_degraded'): return 0.5
        trend_map = {'UP': 1.0, 'SIDEWAYS': 0.5, 'DOWN': 0.0}
        base = trend_map.get(output.get('trend', 'SIDEWAYS'), 0.5)
        strength = output.get('trend_strength', 0.5)
        confidence = output.get('confidence', 0.5)
        return (base * 0.6 + strength * 0.4) * (0.5 + confidence * 0.5)

    def _fundamental_to_score(self, output: dict) -> float:
        if output.get('_degraded'): return 0.5
        score = output.get('overall_score', 50) / 100.0
        growth = {'UP': 1.0, 'STABLE': 0.5, 'DOWN': 0.0}.get(
            output.get('growth_outlook', 'STABLE'), 0.5)
        return score * 0.7 + growth * 0.3

    def _sentiment_to_score(self, output: dict) -> float:
        if output.get('_degraded'): return 0.5
        sent = {'POSITIVE': 1.0, 'NEUTRAL': 0.5, 'NEGATIVE': 0.0}.get(
            output.get('sentiment', 'NEUTRAL'), 0.5)
        heat = output.get('heat_score', 50) / 100.0
        return sent * 0.7 + heat * 0.3

    def _shortterm_to_score(self, output: dict) -> float:
        if output.get('_degraded'): return 0.5
        sig = {'BUY': 1.0, 'HOLD': 0.5, 'SELL': 0.1, 'AVOID': 0.0}.get(
            output.get('short_term_signal', 'HOLD'), 0.5)
        confidence = output.get('confidence', 0.5)
        return sig * 0.7 + confidence * 0.3

    def _risk_to_score(self, output: dict) -> float:
        score = output.get('risk_score', 50) / 100.0
        return score

    def _adjust_weights_for_degraded(self, degraded: list) -> dict:
        weights = dict(self.WEIGHTS)
        if not degraded: return weights
        lost_weight = sum(weights[name] for name in degraded if name in weights)
        active = [name for name in weights if name not in degraded]
        extra = lost_weight / len(active) if active else 0
        for name in degraded:
            weights[name] = 0
        for name in active:
            weights[name] += extra
        return weights

    def _build_reason(self, action: str, results: dict, scores: dict) -> str:
        parts = []
        t = results.get('trend', {})
        t_out = t.output if hasattr(t, 'output') else t
        if not t_out.get('_degraded'):
            parts.append(f"趋势{t_out.get('trend', '?')}（强度{t_out.get('trend_strength', 0):.0%}）")

        f = results.get('fundamental', {})
        f_out = f.output if hasattr(f, 'output') else f
        if not f_out.get('_degraded'):
            parts.append(f"基本面评级{f_out.get('grade', '?')}（{f_out.get('growth_outlook', '?')}）")

        s = results.get('sentiment', {})
        s_out = s.output if hasattr(s, 'output') else s
        if not s_out.get('_degraded'):
            parts.append(f"市场情绪{s_out.get('sentiment', '?')}")

        risk = results.get('risk', {})
        if risk.get('issues'):
            parts.append(f"风险提示：{risk['issues'][0]}")

        return "；".join(parts) if parts else f"综合AI分析，建议{action}"
```
