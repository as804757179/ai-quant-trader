# 55 — 决策可解释性、可信度引擎与知识沉淀（Decision Trace, Confidence & Knowledge Base）

> 优先级：**P1**。本文档整合三个原始提案（Decision Trace可解释性、Confidence Engine可信度引擎、Failure Library失败案例库+Knowledge Base经验知识库），因为它们在数据结构和使用场景上高度耦合：可信度评分需要决策链路数据作为输入，失败案例库本质是决策链路数据的一个筛选视图，知识库则是对失败案例的归纳总结。

---

## 1. 为什么需要新增

`15_16_AI_ARCHITECTURE_AGENTS.md`的`SignalAggregator`已经输出了`agent_votes`（各Agent原始结果）和`confidence`（最终聚合置信度），看起来已经具备"可解释性"。但实际上这只是**结果的展示**，不是**决策过程的结构化记录**。当某次BUY信号在3天后导致8%亏损时，现有系统只能告诉你"当时trend agent说UP，fundamental agent说B+"，但回答不了这几个关键问题：

第一，这次的置信度0.72是怎么算出来的，是因为各Agent高度一致，还是因为某个Agent给了极端值把平均值拉高了？第二，类似的市场环境和个股特征，历史上出现过多少次，平均结果如何？第三，这次失败和过去的失败案例有什么共性，是否本可以提前识别？

现有的`confidence`字段是一个单一数字，无法回答任何一个"为什么"。这正是用户原始提案中#13（决策链可解释）、#5（不要只有一个confidence字段）、#6+#7（失败案例库和经验知识库）共同指向的问题：**系统缺少从"做了什么决策"到"为什么做这个决策"再到"这个决策事后看对不对，能学到什么"的完整闭环**。

## 2. 设计目标

```
1. 把现有 ai.signals 表的 agent_votes（一个JSONB字段）升级为结构化的"决策链路"，记录每个维度对最终决策的贡献度，支持完整回放
2. 在 SignalAggregator 现有的单一 confidence 基础上，新增 OverallConfidenceScore，综合历史命中率、相似行情表现、数据质量、市场状态一致性等维度
3. 自动识别"失败交易"（信号执行后实际亏损超过阈值），结构化记录失败案例，与决策链路数据关联
4. 提供失败案例的检索能力，供后续同类决策时做参考预警（不是自动阻断，是提示）
5. 建立"复盘→提炼经验→反哺Prompt"的人工审核闭环（不做全自动化，因为自动修改Prompt有失控风险）
```

## 3. 核心功能

```
DecisionTraceBuilder：将一次完整的AI分析过程组装成结构化决策链
ConfidenceEngine：综合多维度计算 Overall Confidence Score
FailureDetector：定时扫描已平仓/已过期信号，自动识别失败案例
FailureLibrary：失败案例的存储与检索
KnowledgeDistiller：（人工触发为主）从一批失败案例中提炼"Lesson Learned"
SimilarCaseRetriever：为新的分析请求检索历史相似案例，作为决策参考
```

### 3.1 决策链路构建器

```python
# backend/app/decision_trace/builder.py

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

@dataclass
class DecisionFactor:
    """单个决策因素的贡献度记录"""
    factor_name: str        # 如 "trend_agent" / "fundamental_agent" / "market_state" / "data_quality"
    raw_value: dict          # 该因素的原始输出
    weight: float             # 在最终决策中的权重
    contribution_score: float # 加权后的贡献分（可正可负）
    direction: str            # POSITIVE/NEGATIVE/NEUTRAL

@dataclass
class DecisionTrace:
    """完整决策链路，可序列化存储和事后回放"""
    signal_id: str
    stock_code: str
    final_action: str
    final_confidence: float
    factors: List[DecisionFactor] = field(default_factory=list)
    market_state_at_decision: Optional[dict] = None
    data_quality_at_decision: Optional[float] = None
    similar_historical_cases: List[dict] = field(default_factory=list)
    decision_summary: str = ""
    created_at: str = ""

class DecisionTraceBuilder:
    """
    在 SignalAggregator.aggregate()（15_16文档）执行完毕后调用
    把分散在各处的中间结果组装成统一的、可解释的决策链
    """

    def build(
        self,
        signal: dict,                 # SignalAggregator.aggregate() 的输出
        agent_results: dict,          # 原始的各Agent AgentResult对象
        market_state: Optional[dict], # 51文档的市场状态（若已实现）
        data_quality_score: Optional[float],  # 54文档的质量分（若已实现）
        similar_cases: List[dict],    # SimilarCaseRetriever 的检索结果
    ) -> DecisionTrace:
        factors = []

        # 各Agent作为决策因素（权重对应15_16文档SignalAggregator.WEIGHTS）
        agent_weights = {'trend': 0.30, 'fundamental': 0.25, 'sentiment': 0.20,
                         'shortterm': 0.15, 'risk': 0.10}

        for name, weight in agent_weights.items():
            result = agent_results.get(name)
            if result is None:
                continue
            output = result.output if hasattr(result, 'output') else result
            score = signal.get('scores', {}).get(name, 0.5)
            contribution = (score - 0.5) * weight * 2  # 归一化到 -weight ~ +weight 范围

            factors.append(DecisionFactor(
                factor_name=f"{name}_agent",
                raw_value=output,
                weight=weight,
                contribution_score=round(contribution, 4),
                direction='POSITIVE' if contribution > 0.02 else 'NEGATIVE' if contribution < -0.02 else 'NEUTRAL'
            ))

        # 市场状态作为决策因素（若51文档已实现）
        if market_state:
            factors.append(DecisionFactor(
                factor_name='market_state',
                raw_value=market_state,
                weight=0.0,  # 市场状态不直接计入置信度权重，而是作为筛选闸门（51文档的StrategySelector）
                contribution_score=0.0,
                direction='NEUTRAL'
            ))

        summary = self._build_human_readable_summary(factors, signal)

        return DecisionTrace(
            signal_id=signal['id'],
            stock_code=signal['stock_code'],
            final_action=signal['action'],
            final_confidence=signal['confidence'],
            factors=factors,
            market_state_at_decision=market_state,
            data_quality_at_decision=data_quality_score,
            similar_historical_cases=similar_cases,
            decision_summary=summary,
            created_at=datetime.utcnow().isoformat(),
        )

    def _build_human_readable_summary(self, factors: List[DecisionFactor], signal: dict) -> str:
        """生成类似用户示例中"资金流：+20 行业：+18 新闻：+15..."的可读摘要"""
        lines = []
        for f in sorted(factors, key=lambda x: -abs(x.contribution_score)):
            if f.weight == 0:
                continue
            sign = '+' if f.contribution_score >= 0 else ''
            lines.append(f"{f.factor_name}：{sign}{f.contribution_score*100:.0f}")
        lines.append(f"最终置信度：{signal['confidence']*100:.0f}")
        return '\n'.join(lines)
```

### 3.2 可信度引擎

```python
# backend/app/decision_trace/confidence_engine.py

from dataclasses import dataclass
import numpy as np

@dataclass
class ConfidenceBreakdown:
    raw_agent_confidence: float       # 原始SignalAggregator输出的confidence
    historical_hit_rate_score: float  # 该策略/该Agent组合的历史命中率
    similar_case_score: float          # 相似历史案例的平均表现
    data_quality_score: float          # 来自54文档
    market_consistency_score: float    # 当前市场状态与策略适用性的匹配度（来自51文档）
    agent_agreement_score: float       # 各Agent之间的一致性（分歧越小这项越高）
    overall_score: float                # 最终综合分

class ConfidenceEngine:
    """
    不替代 SignalAggregator 的 confidence 计算（15_16文档），而是在其结果之上做二次校准
    解决"原始confidence可能因单个Agent极端值被拉高/拉低"的问题
    """

    WEIGHTS = {
        'raw_agent_confidence': 0.35,
        'historical_hit_rate': 0.20,
        'similar_case': 0.15,
        'data_quality': 0.15,
        'market_consistency': 0.10,
        'agent_agreement': 0.05,
    }

    async def calculate(
        self,
        signal: dict,
        agent_results: dict,
        data_quality_score: float,
        market_regime: str,
        strategy_type: str,
        db,
    ) -> ConfidenceBreakdown:
        raw_confidence = signal['confidence']

        historical_score = await self._calc_historical_hit_rate(
            stock_code=signal['stock_code'], strategy_type=strategy_type, db=db
        )

        similar_score = await self._calc_similar_case_score(
            stock_code=signal['stock_code'], market_regime=market_regime, db=db
        )

        quality_score = (data_quality_score or 80) / 100.0

        consistency_score = self._calc_market_consistency(strategy_type, market_regime)

        agreement_score = self._calc_agent_agreement(agent_results)

        overall = (
            raw_confidence * self.WEIGHTS['raw_agent_confidence'] +
            historical_score * self.WEIGHTS['historical_hit_rate'] +
            similar_score * self.WEIGHTS['similar_case'] +
            quality_score * self.WEIGHTS['data_quality'] +
            consistency_score * self.WEIGHTS['market_consistency'] +
            agreement_score * self.WEIGHTS['agent_agreement']
        )

        return ConfidenceBreakdown(
            raw_agent_confidence=round(raw_confidence, 4),
            historical_hit_rate_score=round(historical_score, 4),
            similar_case_score=round(similar_score, 4),
            data_quality_score=round(quality_score, 4),
            market_consistency_score=round(consistency_score, 4),
            agent_agreement_score=round(agreement_score, 4),
            overall_score=round(overall, 4),
        )

    async def _calc_historical_hit_rate(self, stock_code: str, strategy_type: str, db) -> float:
        """该股票/该策略类型历史信号的实际命中率（基于ai.signals表的pnl字段回填结果）"""
        row = await db.fetchone("""
            SELECT
                COUNT(*) FILTER (WHERE pnl > 0) AS wins,
                COUNT(*) AS total
            FROM ai.signals
            WHERE stock_code = $1 AND status = 'executed'
              AND signal_time > NOW() - INTERVAL '180 days'
        """, stock_code)
        if not row or row['total'] < 5:
            return 0.5  # 样本不足时返回中性值，不应过度自信也不应过度悲观
        return row['wins'] / row['total']

    async def _calc_similar_case_score(self, stock_code: str, market_regime: str, db) -> float:
        """相似市场状态下，同行业股票的历史信号平均表现"""
        row = await db.fetchone("""
            SELECT AVG(CASE WHEN s.pnl > 0 THEN 1.0 ELSE 0.0 END) as avg_win
            FROM ai.signals s
            JOIN fundamental.stocks st ON s.stock_code = st.code
            JOIN fundamental.stocks st2 ON st2.code = $1
            WHERE st.sector = st2.sector AND s.status = 'executed'
              AND s.signal_time > NOW() - INTERVAL '90 days'
        """, stock_code)
        return float(row['avg_win']) if row and row['avg_win'] is not None else 0.5

    def _calc_market_consistency(self, strategy_type: str, market_regime: str) -> float:
        """依赖51文档的StrategySelector判断当前策略是否适配当前市场状态"""
        try:
            from app.market_state.strategy_selector import StrategySelector
            from app.market_state.regime import MarketRegime
            selector = StrategySelector()
            is_allowed = selector.is_strategy_allowed(strategy_type, MarketRegime(market_regime))
            return 1.0 if is_allowed else 0.3
        except (ImportError, ValueError):
            return 0.7  # 51文档未实现或市场状态未知时，给中性偏积极的默认值，不阻断

    def _calc_agent_agreement(self, agent_results: dict) -> float:
        """各Agent置信度的一致性：标准差越小，一致性越高"""
        confidences = []
        for r in agent_results.values():
            output = r.output if hasattr(r, 'output') else r
            if not output.get('_degraded') and 'confidence' in output:
                confidences.append(output['confidence'])
        if len(confidences) < 2:
            return 0.5
        std = np.std(confidences)
        return max(0, 1 - std * 2)  # 标准差0=完全一致(1.0分)，标准差0.5+=分歧很大(0分)
```

### 3.3 失败检测与案例库

```python
# backend/app/knowledge/failure_detector.py

class FailureDetector:
    """
    定时扫描已执行且已平仓（或已过期）的信号，识别失败案例
    "失败"的定义：信号建议BUY，实际执行后最终亏损超过阈值
    """

    FAILURE_LOSS_THRESHOLD = -0.05   # 亏损超过5%视为失败案例

    async def scan_and_record(self, db):
        candidates = await db.fetch("""
            SELECT s.*
            FROM ai.signals s
            WHERE s.status = 'executed'
              AND s.pnl_pct IS NOT NULL
              AND s.pnl_pct < $1
              AND NOT EXISTS (
                  SELECT 1 FROM knowledge.failure_cases fc WHERE fc.signal_id = s.id
              )
        """, self.FAILURE_LOSS_THRESHOLD * 100)

        for signal in candidates:
            await self._record_failure_case(signal, db)

    async def _record_failure_case(self, signal: dict, db):
        # 拉取该信号决策时刻的完整上下文（来自decision_trace）
        trace = await db.fetchone("""
            SELECT * FROM decision_trace.traces WHERE signal_id = $1
        """, signal['id'])

        # 拉取决策后的关键新闻（事后归因：是否有信号生成时未捕捉到的重大利空）
        post_signal_news = await db.fetch("""
            SELECT title, publish_time FROM fundamental.announcements
            WHERE stock_code = $1 AND publish_time BETWEEN $2 AND $3
            ORDER BY publish_time LIMIT 5
        """, signal['stock_code'], signal['signal_time'], signal.get('executed_at'))

        failure_reason = await self._classify_failure_reason(signal, trace, post_signal_news)

        await db.execute("""
            INSERT INTO knowledge.failure_cases
            (signal_id, stock_code, signal_time, market_state_snapshot,
             agent_analysis_snapshot, post_signal_news, pnl_pct,
             stop_loss_triggered, failure_category, failure_reason)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        """, signal['id'], signal['stock_code'], signal['signal_time'],
             trace['market_state_at_decision'] if trace else None,
             signal['agent_votes'],
             [dict(n) for n in post_signal_news],
             signal['pnl_pct'],
             signal['pnl_pct'] <= -5.0,
             failure_reason['category'],
             failure_reason['detail'])

    async def _classify_failure_reason(self, signal, trace, post_news) -> dict:
        """
        失败归因分类（规则优先，避免每次都调用LLM增加成本）
        无法分类的标记为UNKNOWN，留给人工复盘，不自动调用LLM做归因
        """
        if post_news:
            return {'category': 'UNFORESEEN_NEWS', 'detail': f"信号后出现相关新闻：{post_news[0]['title']}"}

        if trace and trace.get('agent_agreement_score', 1.0) < 0.4:
            return {'category': 'AGENT_DISAGREEMENT', 'detail': "各Agent分析结果分歧较大，但仍生成了交易信号"}

        if signal['pnl_pct'] <= -8.0:
            return {'category': 'SEVERE_DRAWDOWN', 'detail': "亏损幅度远超正常止损范围，可能存在止损执行延迟"}

        return {'category': 'UNKNOWN', 'detail': '需人工复盘归因'}
```

### 3.4 经验知识库（人工主导的提炼流程）

```python
# backend/app/knowledge/distiller.py

class KnowledgeDistiller:
    """
    刻意设计为半自动：系统负责"聚合相似失败案例供人审阅"，
    "提炼为Lesson Learned并决定是否反哺Prompt"这一步必须人工确认

    原因：自动修改Agent Prompt是有风险的操作，错误的归纳可能导致Prompt劣化
    """

    async def suggest_lessons(self, db, lookback_days: int = 30) -> list:
        """
        按 failure_category 聚类近期失败案例，找出重复出现的模式
        返回供人工审阅的候选Lesson列表，不直接写入正式知识库
        """
        clusters = await db.fetch("""
            SELECT failure_category, COUNT(*) as count,
                   array_agg(stock_code) as stock_codes,
                   array_agg(signal_id) as signal_ids
            FROM knowledge.failure_cases
            WHERE created_at > NOW() - INTERVAL '%s days'
            GROUP BY failure_category
            HAVING COUNT(*) >= 3
            ORDER BY count DESC
        """ % lookback_days)

        suggestions = []
        for cluster in clusters:
            suggestions.append({
                'category': cluster['failure_category'],
                'occurrence_count': cluster['count'],
                'affected_stocks': cluster['stock_codes'][:10],
                'related_signal_ids': cluster['signal_ids'],
                'suggested_lesson_draft': self._draft_lesson_text(cluster['failure_category'], cluster['count']),
                'status': 'PENDING_REVIEW',
            })
        return suggestions

    def _draft_lesson_text(self, category: str, count: int) -> str:
        templates = {
            'UNFORESEEN_NEWS': f"近期{count}次失败案例均涉及信号生成后出现未预判的新闻，建议加强SentimentAgent对潜在风险新闻的前瞻性扫描",
            'AGENT_DISAGREEMENT': f"近期{count}次失败案例中Agent分歧度较大，建议提高SignalAggregator在高分歧情况下的置信度惩罚力度",
            'SEVERE_DRAWDOWN': f"近期{count}次案例出现远超预期的回撤，建议复核止损执行链路（35_38文档OrderManager）是否存在延迟",
        }
        return templates.get(category, f"出现{count}次{category}类型失败，需人工归纳具体原因")

    async def confirm_lesson(self, lesson_id: int, final_text: str, operator: str, db):
        """人工确认后才正式写入知识库"""
        await db.execute("""
            UPDATE knowledge.lessons_learned
            SET status = 'CONFIRMED', final_text = $1, confirmed_by = $2, confirmed_at = NOW()
            WHERE id = $3
        """, final_text, operator, lesson_id)


class SimilarCaseRetriever:
    """
    新信号生成时，检索历史相似案例（含成功和失败），供DecisionTraceBuilder使用
    """

    async def retrieve(self, stock_code: str, market_regime: str, context: dict, db) -> list:
        sector = await db.fetchval("SELECT sector FROM fundamental.stocks WHERE code = $1", stock_code)

        similar = await db.fetch("""
            SELECT s.id, s.stock_code, s.action, s.confidence, s.pnl_pct, s.signal_time
            FROM ai.signals s
            JOIN fundamental.stocks st ON s.stock_code = st.code
            WHERE st.sector = $1 AND s.status = 'executed'
              AND s.signal_time > NOW() - INTERVAL '180 days'
            ORDER BY s.signal_time DESC LIMIT 10
        """, sector)

        return [dict(r) for r in similar]
```

## 4. 系统架构

```
信号生成完成（SignalAggregator.aggregate()，15_16文档不变）
            │
            ▼
┌───────────────────────────┐
│  SimilarCaseRetriever      │ ← 检索历史相似案例（同行业近180天）
│  .retrieve()                │
└─────────────┬───────────────┘
              ▼
┌───────────────────────────┐
│  DecisionTraceBuilder       │ ← 组装完整决策链（各因素贡献度）
│  .build()                    │
└─────────────┬───────────────┘
              ▼
┌───────────────────────────┐
│  ConfidenceEngine            │ ← 计算综合可信度（6维度，区别于原始confidence）
│  .calculate()                 │
└─────────────┬───────────────┘
              ▼
   写入 decision_trace.traces 表
   signal.decision_trace_id 关联


【异步，独立运行——每日收盘后】
   FailureDetector.scan_and_record()
            │
            ▼
   写入 knowledge.failure_cases


【人工触发——建议每周一次】
   KnowledgeDistiller.suggest_lessons()
            │
            ▼
   人工审阅 → confirm_lesson() → CONFIRMED状态
            │
            ▼
   （人工后续）将Lesson整合进对应Agent的Prompt模板
   （系统不自动修改Prompt，只记录"已应用"标记）
```

## 5. 数据流

```
1. AgentOrchestrator.analyze()（15_16文档）执行完毕，得到 signal 和 agent_results
2. 新增：SimilarCaseRetriever.retrieve() 查询历史相似案例
3. 新增：DecisionTraceBuilder.build() 组装决策链，写入 decision_trace.traces
4. 新增：ConfidenceEngine.calculate() 计算综合可信度，写入 traces.overall_confidence_score
5. 信号正常存入 ai.signals（15_16文档原有逻辑），新增字段关联 decision_trace_id
6. 信号执行后，35_38文档原有的成交流程会回填 ai.signals.pnl/pnl_pct（已有逻辑）
7. 每日收盘后，FailureDetector 扫描当日新产生pnl数据的信号，识别失败案例
8. 失败案例写入 knowledge.failure_cases，关联到对应的 decision_trace
9. 运营人员定期（建议每周）调用 suggest_lessons 接口，查看聚类后的失败模式
10. 人工审阅确认后，写入 knowledge.lessons_learned（最终是否反哺Prompt是人工决定）
```

## 6. 数据库设计（新增数据表）

```sql
CREATE SCHEMA IF NOT EXISTS decision_trace;
CREATE SCHEMA IF NOT EXISTS knowledge;

-- 决策链路完整记录
CREATE TABLE decision_trace.traces (
    id                          UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    signal_id                   UUID            NOT NULL REFERENCES ai.signals(id),
    stock_code                  VARCHAR(10)     NOT NULL,
    final_action                VARCHAR(10)     NOT NULL,
    final_confidence            NUMERIC(5,4)    NOT NULL,
    factors                     JSONB           NOT NULL,    -- List[DecisionFactor]序列化
    market_state_at_decision    JSONB,
    data_quality_at_decision    NUMERIC(5,2),
    similar_historical_cases    JSONB,
    decision_summary            TEXT,           -- 可读摘要（"trend_agent：+22 fundamental_agent：+15..."）

    -- ConfidenceEngine 输出（区别于signal原有的单一confidence）
    raw_agent_confidence        NUMERIC(5,4),
    historical_hit_rate_score   NUMERIC(5,4),
    similar_case_score          NUMERIC(5,4),
    data_quality_score          NUMERIC(5,4),
    market_consistency_score    NUMERIC(5,4),
    agent_agreement_score       NUMERIC(5,4),
    overall_confidence_score    NUMERIC(5,4),

    created_at                  TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX idx_decision_trace_signal ON decision_trace.traces(signal_id);
CREATE INDEX idx_decision_trace_stock_time ON decision_trace.traces(stock_code, created_at DESC);

-- 扩展 ai.signals 表，关联决策链
ALTER TABLE ai.signals
    ADD COLUMN decision_trace_id UUID REFERENCES decision_trace.traces(id);

-- 失败案例库
CREATE TABLE knowledge.failure_cases (
    id                      BIGSERIAL       PRIMARY KEY,
    signal_id               UUID            NOT NULL REFERENCES ai.signals(id),
    stock_code              VARCHAR(10)     NOT NULL,
    signal_time             TIMESTAMPTZ     NOT NULL,
    market_state_snapshot   JSONB,
    strategy_type           VARCHAR(50),
    agent_analysis_snapshot JSONB,           -- 决策时刻各Agent的完整输出
    post_signal_news        JSONB,           -- 信号后出现的相关新闻（事后归因用）
    pnl_pct                 NUMERIC(8,4)    NOT NULL,
    stop_loss_triggered     BOOLEAN,
    failure_category        VARCHAR(50)     NOT NULL,   -- UNFORESEEN_NEWS/AGENT_DISAGREEMENT/SEVERE_DRAWDOWN/UNKNOWN
    failure_reason          TEXT,
    human_reviewed          BOOLEAN         DEFAULT FALSE,
    human_review_note       TEXT,
    created_at              TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX idx_failure_cases_category ON knowledge.failure_cases(failure_category, created_at DESC);
CREATE INDEX idx_failure_cases_stock ON knowledge.failure_cases(stock_code);

-- 经验知识库（人工确认后的Lesson Learned）
CREATE TABLE knowledge.lessons_learned (
    id                      BIGSERIAL       PRIMARY KEY,
    category                VARCHAR(50)     NOT NULL,
    occurrence_count        INT             NOT NULL,
    related_failure_case_ids BIGINT[],
    draft_text              TEXT            NOT NULL,
    final_text              TEXT,
    status                  VARCHAR(20)     DEFAULT 'PENDING_REVIEW'
                            CHECK (status IN ('PENDING_REVIEW', 'CONFIRMED', 'REJECTED')),
    confirmed_by            VARCHAR(50),
    confirmed_at            TIMESTAMPTZ,
    applied_to_prompt       BOOLEAN         DEFAULT FALSE,  -- 是否已被人工整理进Prompt（人工标记）
    created_at              TIMESTAMPTZ     DEFAULT NOW()
);
```

## 7. API设计

```
GET  /api/v1/decision-trace/{signal_id}
     获取指定信号的完整决策链路（用于前端"决策回放"展示）

GET  /api/v1/decision-trace/{signal_id}/confidence-breakdown
     获取该信号的ConfidenceEngine详细评分构成

GET  /api/v1/knowledge/failure-cases?category=UNFORESEEN_NEWS&days=30
     查询失败案例列表，支持按分类/时间筛选

GET  /api/v1/knowledge/failure-cases/{id}
     失败案例详情（含完整决策快照）

POST /api/v1/knowledge/suggest-lessons
     触发KnowledgeDistiller聚类分析，返回待审阅的Lesson候选列表

POST /api/v1/knowledge/lessons/{id}/confirm
     人工确认一条Lesson Learned
     Body: {final_text, operator}

GET  /api/v1/knowledge/lessons?status=CONFIRMED
     已确认的经验知识库列表（供团队查阅，也可人工对照检查Prompt是否已更新）
```

## 8. AI Agent职责

**本模块不新增独立的分析型LLM Agent。** `ConfidenceEngine`和`FailureDetector`的核心逻辑都是确定性计算（历史命中率统计、规则分类），刻意不引入LLM参与失败归因——`FailureDetector._classify_failure_reason()`的设计明确说明：只做规则分类，无法分类的标记为`UNKNOWN`交给人工，不自动调用LLM"猜测"失败原因，因为错误的自动归因比"不知道"更危险（会产生虚假的确定性）。

`KnowledgeDistiller.suggest_lessons()`生成的`suggested_lesson_draft`使用的是模板文本而非LLM生成，同样是为了避免自动化文本生成在关键决策知识沉淀环节引入不可控的表述偏差。

## 9. 前端页面设计

新增 **决策回放** 功能，嵌入到现有"AI决策页"（42_44文档已存在）：

```
AI决策页 → 信号历史列表 → 点击任意历史信号
            │
            ▼
   决策回放视图（新增）
   ├── 决策因素瀑布图（ECharts waterfall图）
   │   对应用户示例中"资金流+20 行业+18 新闻+15..."的可视化形式
   │   横轴：各Agent/因素名称
   │   纵轴：贡献度分值（正负）
   │   最右侧：最终置信度汇总
   │
   ├── ConfidenceBreakdown 雷达图（6个维度）
   │   raw_agent_confidence / historical_hit_rate / similar_case
   │   data_quality / market_consistency / agent_agreement
   │
   ├── 相似历史案例列表（点击可跳转查看，含胜负标记）
   └── 若该信号最终是失败案例：显示失败归因标签 + 后续新闻

新增 知识库 独立菜单页面：
├── 失败案例库（表格，可筛选分类/时间/股票，点击查看详情）
├── 待审阅Lesson列表（运营人员审阅入口，可编辑final_text后确认）
└── 已确认经验库（只读列表，供团队参考，标注是否已应用到Prompt）
```

## 10. 定时任务

```python
# 新增到 worker/celery_app.py 的 beat_schedule

'failure-detection-daily': {
    'task': 'tasks.detect_failure_cases',
    'schedule': crontab(hour=16, minute=10),   # 收盘后，晚于35_38文档的对账任务
},
'knowledge-distillation-weekly': {
    'task': 'tasks.generate_lesson_suggestions',
    'schedule': crontab(day_of_week=0, hour=10, minute=0),  # 每周日上午，供周会讨论
},
```

```python
# worker/tasks/knowledge.py

@shared_task(name='tasks.detect_failure_cases', queue='low')
def detect_failure_cases():
    import asyncio
    from app.knowledge.failure_detector import FailureDetector

    async def _run():
        from app.db import get_db
        async with get_db() as db:
            detector = FailureDetector()
            await detector.scan_and_record(db)

    asyncio.run(_run())


@shared_task(name='tasks.generate_lesson_suggestions', queue='low')
def generate_lesson_suggestions():
    """生成候选清单后通过钉钉通知运营人员审阅，不自动确认任何Lesson"""
    import asyncio
    from app.knowledge.distiller import KnowledgeDistiller

    async def _run():
        from app.db import get_db
        async with get_db() as db:
            distiller = KnowledgeDistiller()
            suggestions = await distiller.suggest_lessons(db)
            if suggestions:
                for s in suggestions:
                    await db.execute("""
                        INSERT INTO knowledge.lessons_learned
                        (category, occurrence_count, related_failure_case_ids, draft_text, status)
                        VALUES ($1, $2, $3, $4, 'PENDING_REVIEW')
                    """, s['category'], s['occurrence_count'],
                         s['related_signal_ids'], s['suggested_lesson_draft'])
                # 推送钉钉通知（复用02文档的DINGTALK_WEBHOOK配置）
                await _send_dingtalk_notification(
                    f"本周生成{len(suggestions)}条待审阅经验总结，请前往知识库页面审阅"
                )

    asyncio.run(_run())
```

## 11. 配置项

```env
# ── 决策链与知识库 ──
FAILURE_DETECTION_LOSS_THRESHOLD=-0.05      # 亏损超过此比例视为失败案例
KNOWLEDGE_DISTILLATION_MIN_CLUSTER_SIZE=3   # 至少出现N次同类失败才生成Lesson建议
CONFIDENCE_ENGINE_MIN_SAMPLE_SIZE=5         # 历史命中率计算所需最小样本量（不足则返回中性值0.5）
DECISION_TRACE_RETENTION_DAYS=365           # 决策链路数据保留天数（审计需要，建议长期保留）
```

## 12. 开发优先级

属于 **Phase 4（回测完善）至 Phase 5（实盘接入）之间**的衔接模块。`DecisionTraceBuilder`和`ConfidenceEngine`建议在Phase 4末期实现，此时已有足够的历史信号数据支撑`_calc_historical_hit_rate()`等统计计算产生有意义的结果——样本太少时这些指标会持续返回中性默认值0.5，意义不大。

`FailureDetector`和`KnowledgeDistiller`的价值随着系统运行时间增长而增长，建议作为**Phase 5纸盘验证期间的并行任务**来逐步积累，不需要在实盘开关打开前100%完成。这与51/53/54三个P0模块的"必须先有再运行"性质不同，可以渐进式增强。

## 13. 验收标准（Definition of Done）

```
□ DecisionTraceBuilder.build() 生成的decision_summary格式与用户原始需求示例一致（"trend_agent：+22"格式）
□ ConfidenceEngine.calculate() 在样本不足（<5次历史信号）时返回0.5中性值，不引入虚假置信度
□ FailureDetector 能正确识别pnl_pct < -5%的已执行信号，且不重复记录（已有failure_case的signal跳过）
□ KnowledgeDistiller.suggest_lessons() 仅在同类失败案例≥3次时生成建议，避免对单次偶然事件过度归纳
□ 任何Lesson Learned在 status='CONFIRMED' 之前不会出现在"已确认经验库"前端页面
□ 决策回放页面的瀑布图正确展示各因素贡献度，总和与最终confidence数值逻辑自洽
□ 失败案例的post_signal_news正确关联到该股票在信号后续时间窗口内的实际公告
□ decision_trace.traces表的数据量增长速度可控（每个信号一条记录，不会产生数据膨胀问题）
```

## 14. 与现有系统如何集成

**集成点1：`15_16_AI_ARCHITECTURE_AGENTS.md`的`AgentOrchestrator.analyze()`末尾新增决策链构建步骤：**

```python
# 对 15_16文档 AgentOrchestrator.analyze() 的修改（紧跟在原有Step 4仓位建议之后）
async def analyze(self, stock_code: str, context: dict) -> dict:
    # ... 原有Step 1-4逻辑完全不变 ...

    # 新增：构建决策链路（旁路记录，不影响signal本身的返回结构）
    from app.decision_trace.builder import DecisionTraceBuilder
    from app.decision_trace.confidence_engine import ConfidenceEngine
    from app.knowledge.failure_detector import SimilarCaseRetriever

    try:
        retriever = SimilarCaseRetriever()
        similar_cases = await retriever.retrieve(
            stock_code, context.get('market_regime', 'UNKNOWN'), context, self.db
        )

        trace_builder = DecisionTraceBuilder()
        trace = trace_builder.build(
            signal, agent_results,
            market_state=context.get('market_regime'),
            data_quality_score=context.get('data_quality_score'),
            similar_cases=similar_cases,
        )

        confidence_engine = ConfidenceEngine()
        confidence_breakdown = await confidence_engine.calculate(
            signal, agent_results,
            context.get('data_quality_score'), context.get('market_regime', 'SIDEWAYS'),
            strategy_type=context.get('strategy_type', 'ai_driven'), db=self.db
        )

        trace_id = await self._save_decision_trace(trace, confidence_breakdown)
        signal['decision_trace_id'] = trace_id
        signal['overall_confidence_score'] = confidence_breakdown.overall_score
    except Exception as e:
        # 决策链记录失败不应阻断信号生成主流程（旁路特性）
        logger.warning("decision_trace_failed", code=stock_code, error=str(e))

    return signal
```

**集成点2：与51文档（市场状态）和54文档（数据质量）是松耦合关系。** 本文档代码中所有对`market_state`和`data_quality_score`的引用都做了"若不存在则使用默认值"的防御性处理（如`_calc_market_consistency`捕获`ImportError`），因此**本文档可以独立于51/54两个文档先行实现**，待51/54完成后自动获得更精确的可信度计算，不需要返工。

**集成点3：`35_38_TRADE_EXECUTION.md`的成交回填逻辑无需修改。** `ai.signals.pnl_pct`的回填机制已经存在（信号执行后由交易结算流程更新），`FailureDetector`只是新增了一个读取这个已有字段的下游消费者。

**不需要修改的部分：** `06_INFRA_DATABASE.md`中`ai.signals`表的核心字段不变（只新增`decision_trace_id`一个可空字段，向后兼容）；`SignalAggregator`的聚合算法和权重完全不变，`ConfidenceEngine`是独立的二次评估层，不会反过来影响`signal['confidence']`的原始值，避免循环依赖。
