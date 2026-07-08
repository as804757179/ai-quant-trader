# 51 — 市场状态识别引擎（Market State Engine）

> 优先级：**P0 必须**。AI在分析任何个股之前，必须先判断当前大盘环境。脱离市场环境的个股分析是危险的——同样的"放量突破MA20"信号，在牛市和熊市中的胜率天差地别。

---

## 1. 为什么需要新增

现有系统（15_16文档）的6个Agent全部聚焦**个股**分析：趋势、基本面、情绪、短线、风控、仓位。没有任何一个Agent回答"现在的大盘适不适合做多"这个前置问题。

这会导致一个真实的失败模式：策略回测在2019-2020年牛市数据上表现优异（夏普2.0+），但部署到2022年熊市后大幅跑输，因为策略本身没有"熊市应该空仓或大幅降低仓位"的概念——所有买入信号都是基于个股技术面/基本面生成的，与大盘环境无关。

`31_34_RISK_ENGINE.md` 的风控规则是静态阈值（单票10%、总仓位80%），不会随市场状态自动收紧。`28_29_WALKFORWARD_AUTOML.md` 的Walk-Forward验证虽然能检验策略跨周期表现，但这是回测阶段的事后验证，不是实盘运行时的实时调整机制。

## 2. 设计目标

```
1. 在AgentOrchestrator执行个股分析之前，先完成市场状态判断（前置门禁）
2. 不同市场状态自动映射到不同的策略集合和风控参数
3. 市场状态判断本身要可解释、可回溯，不能是黑盒
4. 状态切换需要"确认机制"，防止单日异常波动造成误判抖动
```

## 3. 核心功能

```
MarketScore：综合打分（0-100），衡量当前市场整体健康度
MarketRegimeDetector：识别7种市场状态中的当前状态
MarketStateAgent：调用LLM对状态做语义层面的解释（政策驱动/题材行情这类需要新闻理解的状态，纯规则判断不出来）
StrategySelector：根据当前状态从策略库中筛选出"适用"的策略子集
状态历史与切换日志：所有状态变更必须落库，供事后复盘
```

### 3.1 市场状态分类与判断逻辑

```python
# backend/app/market_state/regime.py

from enum import Enum
from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np

class MarketRegime(str, Enum):
    BULL = "BULL"                      # 牛市
    BEAR = "BEAR"                      # 熊市
    SIDEWAYS = "SIDEWAYS"              # 震荡市
    HIGH_VOLATILITY = "HIGH_VOLATILITY" # 高波动
    LOW_VOLATILITY = "LOW_VOLATILITY"   # 低波动
    POLICY_DRIVEN = "POLICY_DRIVEN"     # 政策驱动行情
    THEME_DRIVEN = "THEME_DRIVEN"       # 题材行情

@dataclass
class MarketStateResult:
    regime: MarketRegime
    market_score: float           # 0-100
    confidence: float             # 0.0-1.0
    sub_signals: dict             # 各维度子分数
    reason: str
    detected_at: str

class MarketRegimeDetector:
    """
    规则引擎部分：负责趋势/波动率/广度类状态的量化判断
    （BULL/BEAR/SIDEWAYS/HIGH_VOL/LOW_VOL 这5种可以纯规则判断）
    POLICY_DRIVEN/THEME_DRIVEN 需要MarketStateAgent的语义判断兜底
    """

    LOOKBACK_DAYS = 60

    def detect(self, index_kline: pd.DataFrame, breadth_data: dict) -> MarketStateResult:
        """
        index_kline: 沪深300/上证指数近60日K线（必须是T-1日及之前，防未来函数）
        breadth_data: 市场广度数据 {advance_count, decline_count, limit_up_count, limit_down_count}
        """
        if len(index_kline) < self.LOOKBACK_DAYS:
            return self._insufficient_data_result()

        trend_score = self._calc_trend_score(index_kline)
        volatility_score = self._calc_volatility_score(index_kline)
        breadth_score = self._calc_breadth_score(breadth_data)

        market_score = trend_score * 0.45 + volatility_score * 0.25 + breadth_score * 0.30

        regime = self._classify_regime(trend_score, volatility_score, index_kline)

        return MarketStateResult(
            regime=regime,
            market_score=round(market_score, 2),
            confidence=0.85,  # 规则引擎判断，固定较高置信度
            sub_signals={
                'trend_score': round(trend_score, 2),
                'volatility_score': round(volatility_score, 2),
                'breadth_score': round(breadth_score, 2),
            },
            reason=self._build_reason(regime, trend_score, volatility_score, breadth_score),
            detected_at=pd.Timestamp.now().isoformat(),
        )

    def _calc_trend_score(self, df: pd.DataFrame) -> float:
        """趋势得分：基于MA20/MA60排列 + 近20日涨跌幅"""
        close = df['close']
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        current = close.iloc[-1]
        change_20d = (current / close.iloc[-21] - 1) * 100 if len(close) > 20 else 0

        score = 50  # 中性基准
        if current > ma20 > ma60:
            score += 25  # 多头排列
        elif current < ma20 < ma60:
            score -= 25  # 空头排列

        score += np.clip(change_20d * 1.5, -20, 20)
        return np.clip(score, 0, 100)

    def _calc_volatility_score(self, df: pd.DataFrame) -> float:
        """波动率得分：基于近20日年化波动率，相对历史分位数"""
        returns = df['close'].pct_change().dropna()
        recent_vol = returns.tail(20).std() * np.sqrt(252) * 100
        historical_vol = returns.std() * np.sqrt(252) * 100

        if historical_vol == 0:
            return 50
        relative_vol = recent_vol / historical_vol

        # 波动率得分：100=极低波动，0=极高波动（用于后续分类，不是"好坏"）
        return np.clip(100 - (relative_vol - 1) * 50, 0, 100)

    def _calc_breadth_score(self, breadth: dict) -> float:
        """市场广度：涨跌家数比 + 涨跌停比"""
        advance = breadth.get('advance_count', 0)
        decline = breadth.get('decline_count', 1)
        limit_up = breadth.get('limit_up_count', 0)
        limit_down = breadth.get('limit_down_count', 0)

        ad_ratio = advance / (advance + decline) if (advance + decline) > 0 else 0.5
        limit_ratio_score = np.clip((limit_up - limit_down) * 2 + 50, 0, 100)

        return ad_ratio * 100 * 0.6 + limit_ratio_score * 0.4

    def _classify_regime(self, trend_score: float, volatility_score: float, df: pd.DataFrame) -> MarketRegime:
        # 波动率优先判断（极端波动覆盖趋势判断）
        if volatility_score < 25:
            return MarketRegime.HIGH_VOLATILITY
        if volatility_score > 85 and 40 <= trend_score <= 60:
            return MarketRegime.LOW_VOLATILITY

        if trend_score >= 68:
            return MarketRegime.BULL
        if trend_score <= 32:
            return MarketRegime.BEAR
        return MarketRegime.SIDEWAYS

    def _build_reason(self, regime, trend, vol, breadth) -> str:
        return (f"趋势分{trend:.0f} 波动分{vol:.0f} 广度分{breadth:.0f}，"
                f"综合判定为{regime.value}")

    def _insufficient_data_result(self) -> MarketStateResult:
        return MarketStateResult(
            regime=MarketRegime.SIDEWAYS, market_score=50, confidence=0.0,
            sub_signals={}, reason="历史数据不足，无法判断市场状态（默认震荡市，降级处理）",
            detected_at=pd.Timestamp.now().isoformat()
        )
```

### 3.2 Market State Agent（语义层判断）

```python
# backend/app/ai/agents/market_state_agent.py

from .base_agent import BaseAgent

class MarketStateAgent(BaseAgent):
    """
    判断 POLICY_DRIVEN（政策驱动）和 THEME_DRIVEN（题材行情）
    这两种状态无法用纯量化规则识别，需要LLM理解近期新闻/政策语义
    与 MarketRegimeDetector 的规则结果做"二次确认或覆盖"
    """
    name = "market_state"
    model = "claude-3-5-sonnet-20241022"

    SYSTEM_PROMPT = """你是A股宏观策略分析师，专注判断当前市场驱动逻辑。
你的任务不是判断涨跌方向，而是判断"当前行情的驱动力是什么"。
你只输出JSON。"""

    USER_PROMPT_TEMPLATE = """基于以下信息判断当前A股市场的驱动逻辑：

量化引擎初判：{rule_based_regime}（趋势分{trend_score} 波动分{vol_score}）

近5日重大政策新闻：
{policy_news}

近5日市场热门题材及板块涨幅排行：
{theme_rankings}

行业轮动情况：
{sector_rotation}

请判断：
1. 当前是否存在明显的政策驱动特征（货币政策/产业政策/监管政策导致的系统性影响）
2. 当前是否存在明显的题材炒作特征（资金集中涌入少数概念股，与基本面脱钩）
3. 如果都不明显，维持量化引擎的判断

严格按以下JSON输出：
{{
  "override_regime": "POLICY_DRIVEN",
  "should_override": true,
  "policy_factors": ["央行降准0.5个百分点", "证监会出台减持新规"],
  "theme_factors": [],
  "affected_sectors": ["银行", "地产", "券商"],
  "confidence": 0.75,
  "reason": "本周央行宣布降准，叠加证监会新规，金融板块普遍异动，呈现明显政策驱动特征，建议覆盖量化引擎的SIDEWAYS判断"
}}

注意：
- should_override=false 时，override_regime填量化引擎原判断
- 只有证据充分时才override，避免对每日新闻噪音过度反应"""

    async def analyze(self, context: dict) -> dict:
        import anthropic
        prompt = self.USER_PROMPT_TEMPLATE.format(
            rule_based_regime=context['rule_based_regime'],
            trend_score=context['trend_score'],
            vol_score=context['volatility_score'],
            policy_news=context.get('policy_news_str', '无重大政策新闻'),
            theme_rankings=context.get('theme_rankings_str', '无明显题材'),
            sector_rotation=context.get('sector_rotation_str', '数据不可用'),
        )
        client = anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=self.model, max_tokens=600, temperature=0.1,
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )
        self.last_input_tokens = response.usage.input_tokens
        self.last_output_tokens = response.usage.output_tokens
        return self._parse_json_response(response.content[0].text)

    def get_neutral_result(self) -> dict:
        return {
            "should_override": False, "override_regime": None,
            "confidence": 0.0, "reason": "语义判断不可用，使用量化引擎结果",
            "_degraded": True
        }
```

### 3.3 Strategy Selector（状态→策略映射）

```python
# backend/app/market_state/strategy_selector.py

from app.market_state.regime import MarketRegime

class StrategySelector:
    """
    根据当前市场状态，决定：
    1. 哪些策略类型被允许运行
    2. 全局仓位上限的临时调整系数
    3. 信号置信度阈值的临时调整
    """

    # 状态 → 策略适用性矩阵
    REGIME_STRATEGY_MAP = {
        MarketRegime.BULL: {
            'allowed_types': ['ma_crossover', 'macd', 'ai_driven', 'hybrid'],
            'position_multiplier': 1.0,       # 正常仓位
            'confidence_adjustment': 0.0,      # 不调整阈值
            'note': '牛市环境，趋势策略权重提升'
        },
        MarketRegime.BEAR: {
            'allowed_types': ['rsi'],          # 熊市只允许超卖反弹类策略，严格限制
            'position_multiplier': 0.4,        # 仓位打4折
            'confidence_adjustment': 0.10,     # 提高信号门槛
            'note': '熊市环境，大幅降低仓位上限，仅允许超卖反弹型策略'
        },
        MarketRegime.SIDEWAYS: {
            'allowed_types': ['bollinger', 'rsi', 'hybrid'],
            'position_multiplier': 0.7,
            'confidence_adjustment': 0.05,
            'note': '震荡市，适合均值回归类策略'
        },
        MarketRegime.HIGH_VOLATILITY: {
            'allowed_types': ['rsi'],
            'position_multiplier': 0.3,
            'confidence_adjustment': 0.15,
            'note': '高波动环境，大幅收紧风险敞口'
        },
        MarketRegime.LOW_VOLATILITY: {
            'allowed_types': ['ma_crossover', 'macd', 'ai_driven', 'hybrid'],
            'position_multiplier': 1.0,
            'confidence_adjustment': -0.05,    # 低波动环境可适度放宽
            'note': '低波动环境，正常或略积极配置'
        },
        MarketRegime.POLICY_DRIVEN: {
            'allowed_types': ['hybrid', 'ai_driven'],   # 需要AI理解政策影响，纯技术策略不可靠
            'position_multiplier': 0.6,
            'confidence_adjustment': 0.10,
            'note': '政策驱动行情，依赖AI对政策影响的解读，技术面策略降权'
        },
        MarketRegime.THEME_DRIVEN: {
            'allowed_types': ['ai_driven'],
            'position_multiplier': 0.5,
            'confidence_adjustment': 0.15,
            'note': '题材炒作行情，与基本面脱钩，严格限制仓位并提高信号门槛'
        },
    }

    def get_config(self, regime: MarketRegime) -> dict:
        return self.REGIME_STRATEGY_MAP.get(regime, self.REGIME_STRATEGY_MAP[MarketRegime.SIDEWAYS])

    def is_strategy_allowed(self, strategy_type: str, regime: MarketRegime) -> bool:
        config = self.get_config(regime)
        return strategy_type in config['allowed_types']

    def adjust_signal_confidence_threshold(self, base_threshold: float, regime: MarketRegime) -> float:
        config = self.get_config(regime)
        return min(base_threshold + config['confidence_adjustment'], 0.95)

    def adjust_position_limit(self, base_limit: float, regime: MarketRegime) -> float:
        config = self.get_config(regime)
        return base_limit * config['position_multiplier']
```

## 4. 系统架构

```
                    ┌──────────────────────┐
                    │ Celery Beat（每5分钟）│
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ tasks.detect_market_  │
                    │       state()         │
                    └──────────┬───────────┘
                               ▼
         ┌─────────────────────┴─────────────────────┐
         ▼                                            ▼
┌──────────────────┐                       ┌──────────────────────┐
│MarketRegimeDetector│                      │  MarketStateAgent     │
│  （量化规则引擎）  │                       │  （LLM语义判断）       │
└──────────┬────────┘                       └──────────┬────────────┘
           │  rule_based_result                          │ override_result
           └──────────────────┬──────────────────────────┘
                               ▼
                    ┌──────────────────────┐
                    │   状态融合 + 防抖动   │
                    │ （连续2次确认才切换） │
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ market_state.current  │ ← Redis（实时读取）
                    │ market_state_history  │ ← PostgreSQL（审计）
                    └──────────┬───────────┘
                               ▼
              ┌────────────────┴────────────────┐
              ▼                                  ▼
  ┌─────────────────────┐          ┌──────────────────────────┐
  │  StrategySelector     │          │  AgentOrchestrator.analyze│
  │ （影响策略筛选+仓位） │          │ （context注入market_state）│
  └─────────────────────┘          └──────────────────────────┘
                                                  │
                                                  ▼
                                    每个个股Agent的Prompt中
                                    都会包含当前市场状态描述
                                    （见 §13 与现有系统集成）
```

## 5. 数据流

```
1. Celery Beat 每5分钟触发 detect_market_state 任务
2. 拉取沪深300近60日K线（必须T-1日及之前，复用 DataService.get_kline）
3. 拉取市场广度数据（涨跌家数/涨跌停数，新增数据源）
4. MarketRegimeDetector 计算规则结果
5. 若规则结果为非极端状态，调用 MarketStateAgent 做语义复核
6. 两个结果融合：语义Agent的override仅在 confidence>0.7 时生效
7. 防抖动：与Redis中上一次状态对比，连续2次（10分钟）判断一致才正式切换
8. 写入 market_state.current（Redis，TTL 600秒）
9. 状态变更时写入 market_state_history（PostgreSQL，永久记录）
10. 状态变更时通过WebSocket推送 channel:market_state
11. run_signal_scan 任务（已有，见39_41文档）在执行前先读取当前市场状态，
    传入 StrategySelector 过滤可用策略和调整仓位系数
```

## 6. 数据库设计（新增数据表）

```sql
-- 市场状态历史记录
CREATE TABLE market.market_state_history (
    id              BIGSERIAL       PRIMARY KEY,
    regime          VARCHAR(20)     NOT NULL,
    market_score    NUMERIC(5,2)    NOT NULL,
    confidence      NUMERIC(5,4)    NOT NULL,
    trend_score     NUMERIC(5,2),
    volatility_score NUMERIC(5,2),
    breadth_score   NUMERIC(5,2),
    rule_based_regime VARCHAR(20),             -- 规则引擎原始判断
    was_overridden  BOOLEAN         DEFAULT FALSE, -- 是否被Agent语义判断覆盖
    override_reason TEXT,
    policy_factors  JSONB,
    theme_factors   JSONB,
    reason          TEXT,
    effective_from  TIMESTAMPTZ     NOT NULL,   -- 状态生效时间
    effective_until TIMESTAMPTZ,                -- 状态结束时间（NULL=当前生效）
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX idx_market_state_time ON market.market_state_history(effective_from DESC);

-- 市场广度数据（每日快照）
CREATE TABLE market.market_breadth (
    date            DATE            PRIMARY KEY,
    advance_count   INT             NOT NULL,
    decline_count   INT             NOT NULL,
    unchanged_count INT             DEFAULT 0,
    limit_up_count  INT             DEFAULT 0,
    limit_down_count INT            DEFAULT 0,
    new_high_count  INT             DEFAULT 0,
    new_low_count   INT             DEFAULT 0,
    total_amount    NUMERIC(20,2),              -- 全市场成交额
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);
```

## 7. API设计

```
GET  /api/v1/market-state/current
     返回当前市场状态、得分、各子维度分数

GET  /api/v1/market-state/history?days=30
     历史状态变化记录（用于前端展示状态切换时间线）

GET  /api/v1/market-state/strategy-config?regime=BULL
     查询指定状态下的策略配置（哪些策略允许运行/仓位系数）

POST /api/v1/market-state/manual-override
     人工手动覆盖当前市场状态（紧急情况下使用，需要operator字段，记录审计日志）
     Body: {regime, reason, operator}
```

## 8. AI Agent职责

| Agent | 职责范围 |
|---|---|
| MarketRegimeDetector | 不是LLM Agent，是纯规则引擎，负责趋势/波动率/广度的量化打分 |
| MarketStateAgent | 唯一新增的LLM Agent，专职判断POLICY_DRIVEN和THEME_DRIVEN这两种规则引擎无法识别的状态，对规则结果做语义复核 |
| 现有6个个股Agent | **不新增Agent**，但每个Agent的Prompt模板都需要在`market_context`中插入当前市场状态描述（见§13集成方式），让个股分析具备大盘环境感知 |

## 9. 前端页面设计

新增 **市场状态条**（不是独立页面，是嵌入Dashboard和AI决策页顶部的常驻组件）：

```tsx
// frontend/src/components/MarketStateBar/index.tsx
// 展示：当前状态Tag（颜色区分）+ MarketScore进度条 + 状态持续时长 + 点击展开子维度分数

布局：
[🐂 牛市] MarketScore: 72/100  已持续 3天2小时  [详情▼]

展开后显示：
- 趋势分 78 | 波动分 65 | 广度分 71
- 当前策略仓位系数：100%
- 当前允许策略类型：ma_crossover, macd, ai_driven, hybrid
- 最近状态切换：2024-01-15 09:35 SIDEWAYS → BULL
```

在 **Risk页面** 新增子区块：市场状态历史时间线（ECharts时间轴图，可视化状态切换历史，用于复盘"某次亏损是否发生在状态误判期间"）

## 10. 定时任务

```python
# 新增到 worker/celery_app.py 的 beat_schedule

'detect-market-state-5min': {
    'task': 'tasks.detect_market_state',
    'schedule': 300.0,  # 每5分钟（交易时段内）
},
'daily-market-breadth-sync': {
    'task': 'tasks.sync_market_breadth',
    'schedule': crontab(hour=15, minute=10),  # 收盘后同步当日广度数据
},
```

```python
# worker/tasks/market_state.py

@shared_task(name='tasks.detect_market_state', queue='normal')
def detect_market_state():
    """每5分钟检测市场状态，含防抖动逻辑"""
    import asyncio
    from app.market_state.regime import MarketRegimeDetector
    from app.ai.agents.market_state_agent import MarketStateAgent
    from app.data.service import DataService
    from app.data.cache import CacheManager

    async def _run():
        svc = DataService()
        cache = CacheManager()
        detector = MarketRegimeDetector()

        index_kline = await svc.get_kline('000300', '1d', 60)  # 沪深300
        breadth = await _get_today_breadth()

        if not index_kline:
            return

        import pandas as pd
        df = pd.DataFrame(index_kline)
        rule_result = detector.detect(df, breadth)

        # 语义复核（仅当规则判断为中性区间时才调用，节省Token）
        final_regime = rule_result.regime
        was_overridden = False
        if rule_result.regime in ('SIDEWAYS', 'BULL', 'BEAR'):
            agent = MarketStateAgent()
            semantic_result = await agent.analyze({
                'rule_based_regime': rule_result.regime.value,
                'trend_score': rule_result.sub_signals.get('trend_score'),
                'volatility_score': rule_result.sub_signals.get('volatility_score'),
                'policy_news_str': await _get_recent_policy_news(),
                'theme_rankings_str': await _get_theme_rankings(),
                'sector_rotation_str': '',
            })
            if semantic_result.get('should_override') and semantic_result.get('confidence', 0) > 0.7:
                final_regime = semantic_result['override_regime']
                was_overridden = True

        # 防抖动：检查上一次状态
        prev = await cache.get('market_state:pending')
        if prev and prev.get('regime') == final_regime:
            # 连续第二次判断一致，正式切换
            await _commit_state_change(final_regime, rule_result, was_overridden)
            await cache.delete('market_state:pending')
        else:
            # 第一次出现该状态，暂存待确认，不立即切换
            await cache.set('market_state:pending', {'regime': final_regime}, ttl=900)

    asyncio.run(_run())
```

## 11. 配置项

```env
# ── 市场状态引擎 ──
MARKET_STATE_DETECT_INTERVAL=300        # 检测间隔（秒）
MARKET_STATE_CONFIRM_CYCLES=2           # 连续确认次数才切换状态（防抖动）
MARKET_STATE_SEMANTIC_OVERRIDE_THRESHOLD=0.70   # 语义Agent覆盖规则判断所需的最低置信度
MARKET_STATE_INDEX_CODE=000300          # 用于判断市场状态的基准指数（默认沪深300）
```

## 12. 开发优先级

属于 **Phase 3（自动化）阶段**，建议在`03_DEVELOPMENT_ROADMAP.md`的Phase 3任务清单中插入，紧跟在"选股系统"之后，因为StrategySelector需要先于"run_signal_scan"批量信号扫描生效，否则Phase 3做出来的自动信号扫描会缺少状态感知这一前置门禁。

不应早于Phase 3，因为依赖：①完整的DataClient/DataService（Phase 1）②AgentOrchestrator框架（Phase 2）③Celery调度基础设施（Phase 3）。

## 13. 验收标准（Definition of Done）

```
□ MarketRegimeDetector 能对历史已知的牛熊市区间正确分类（用2020年牛市/2022年熊市数据回测验证准确率>70%）
□ MarketStateAgent 降级时（_degraded=True）系统继续使用规则引擎结果，不阻断流程
□ 防抖动逻辑生效：单日内市场状态切换次数不超过3次（避免抖动导致策略频繁开关）
□ market_state_history 表完整记录每次状态变更及原因
□ StrategySelector.get_config() 返回的仓位系数能正确传导到 PreTradeRiskChecker（即熊市下单票仓位上限确实从10%降到4%）
□ 前端MarketStateBar组件正确展示当前状态且通过WebSocket实时更新
□ 人工手动覆盖（manual-override）写入审计日志且有operator字段
```

## 14. 与现有系统如何集成

**最关键的集成点：所有6个个股Agent的Prompt必须注入市场状态上下文。**

修改 `15_16_AI_ARCHITECTURE_AGENTS.md` 中 `BaseAgent._build_market_context_str()`，在原有股票信息基础上新增：

```python
def _build_market_context_str(self, context: dict) -> str:
    market_state_section = ""
    if context.get('market_regime'):
        market_state_section = f"""
当前市场状态：{context['market_regime']}（市场综合得分：{context.get('market_score', 'N/A')}/100）
状态说明：{context.get('market_state_reason', '')}
"""
    return market_state_section + f"""
股票代码：{context.get('code')}  ...（原有内容不变）
"""
```

**第二个集成点：`AgentOrchestrator.analyze()`（15_16文档）执行前先查询市场状态：**

```python
async def analyze(self, stock_code: str, context: dict) -> dict:
    # 新增：注入市场状态
    market_state = await self._get_current_market_state()  # 从Redis读取
    context['market_regime'] = market_state['regime']
    context['market_score'] = market_state['market_score']
    context['market_state_reason'] = market_state['reason']

    # 原有逻辑不变...
```

**第三个集成点：`run_signal_scan`任务（39_41文档）在批量扫描前先过滤策略：**

```python
async def run_signal_scan():
    market_state = await _get_current_market_state()
    selector = StrategySelector()
    config = selector.get_config(market_state['regime'])

    active_strategies = await _get_active_strategies()
    # 新增过滤：只运行当前市场状态允许的策略类型
    allowed_strategies = [
        s for s in active_strategies
        if selector.is_strategy_allowed(s['type'], market_state['regime'])
    ]
    # ... 原有扫描逻辑，使用 allowed_strategies 替代全部策略
```

**第四个集成点：`PreTradeRiskChecker`（31_34文档）单票仓位检查时应用状态系数：**

```python
def _check_single_position(self, stock_code, order_value, portfolio) -> CheckResult:
    base_threshold = 0.10
    market_state = self._get_current_market_state()  # 新增
    selector = StrategySelector()
    threshold = selector.adjust_position_limit(base_threshold, market_state['regime'])  # 新增
    # 原有逻辑使用调整后的threshold替代固定的0.10
```

**不需要修改的部分：** 数据库schema中的`ai.signals`表、`SimulationTrader`撮合逻辑、前端K线图组件——这些与市场状态无关，保持原样。
