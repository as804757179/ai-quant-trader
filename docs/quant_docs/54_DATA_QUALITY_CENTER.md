# 54 — 数据质量中心（Data Quality Center）

> 优先级：**P0 必须**。AI分析建立在数据之上，垃圾数据进去，垃圾信号出来——而且AI的语言能力会让垃圾信号听起来很有说服力，这是比明显的系统崩溃更危险的失败模式。

---

## 1. 为什么需要新增

`10_14_DATA_PIPELINE.md`的`DataService._validate_quote()`只做了最基础的校验（价格>0，最高价≥最低价），且只针对实时报价这一种数据类型。K线数据、财务数据、资金流向数据、新闻数据完全没有质量校验环节——数据从`a-stock-data`拉取后，只要HTTP请求成功、JSON能解析，就会被直接喂给AI Agent。

这是一个真实存在的风险点：如果`a-stock-data`某天因为上游数据源故障返回了部分缺失或重复的K线（比如某只股票连续3天的K线数据完全相同，这是常见的数据源故障模式），现有系统不会发现任何异常——`TrendAgent`会拿着这份失真数据正常生成一个"趋势分析"，置信度可能还很高，因为价格"看起来"很平稳。这种静默失败比系统直接报错更危险，因为它不会触发任何告警，会一直产生看似正常实则基于错误数据的交易信号。

`27_BACKTEST_LOOKAHEAD.md`解决的是"用了不该用的未来数据"，这是时间维度的数据正确性问题。本文档解决的是另一个维度："数据本身是否完整、准确、新鲜"，这是质量维度的问题，两者互补但不重叠。

## 2. 设计目标

```
1. 在数据进入AI分析流程之前增加一道质量门禁，不合格数据直接阻断分析（而非静默使用）
2. 质量评分必须可解释（不是黑盒0-100分，要能说清楚扣分原因）
3. 覆盖现有系统中所有数据类型：行情/K线/财务/资金流/新闻
4. 质量检查本身的开销要可控，不能让每次AI分析都额外增加显著延迟
```

## 3. 核心功能

```
DataQualityChecker：核心检测器，对单个数据类型做质量评分
DataQualityScore：综合评分模型（完整率/重复率/延迟/缺失值/异常值/可信度六个维度）
QualityGate：评分低于阈值时阻断后续AI分析流程
QualityMonitor：持续巡检数据库中已存储数据的质量趋势（不只是实时拦截，也要发现历史数据的渐进式劣化）
```

### 3.1 质量评分模型

```python
# backend/app/data_quality/checker.py

from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

@dataclass
class QualityIssue:
    dimension: str        # completeness/duplication/timeliness/missing_values/outliers/reliability
    severity: str          # CRITICAL/WARNING/INFO
    description: str
    penalty: float          # 扣分值

@dataclass
class DataQualityResult:
    data_type: str
    stock_code: str
    overall_score: float    # 0-100
    dimension_scores: dict
    issues: List[QualityIssue]
    passed: bool             # overall_score >= 阈值
    checked_at: str

class DataQualityChecker:
    """
    六维度质量评分模型：
    1. 完整率（Completeness）：应有数据点 vs 实际数据点
    2. 重复率（Duplication）：异常重复值检测（如连续N天OHLC完全相同）
    3. 时效性（Timeliness）：数据更新时间距当前的延迟
    4. 缺失值（Missing Values）：关键字段为NULL的比例
    5. 异常值（Outliers）：超出合理范围的数值（如涨跌幅超过21%但非新股）
    6. 可信度（Reliability）：跨数据源交叉验证一致性（若有多数据源）
    """

    QUALITY_PASS_THRESHOLD = 80.0   # 低于此分数禁止用于交易决策

    DIMENSION_WEIGHTS = {
        'completeness': 0.25,
        'duplication': 0.15,
        'timeliness': 0.20,
        'missing_values': 0.15,
        'outliers': 0.15,
        'reliability': 0.10,
    }

    def check_kline(self, stock_code: str, klines: List[dict], period: str, expected_count: int) -> DataQualityResult:
        issues = []
        scores = {}

        # 维度1：完整率
        actual_count = len(klines)
        completeness = min(actual_count / expected_count, 1.0) * 100 if expected_count > 0 else 0
        scores['completeness'] = completeness
        if completeness < 90:
            issues.append(QualityIssue(
                'completeness', 'WARNING' if completeness > 70 else 'CRITICAL',
                f"K线数据完整率{completeness:.0f}%，预期{expected_count}条，实际{actual_count}条",
                penalty=(100 - completeness) * 0.25
            ))

        # 维度2：重复率检测（连续N天OHLC完全相同，典型数据源故障特征）
        duplication_score = self._check_kline_duplication(klines)
        scores['duplication'] = duplication_score
        if duplication_score < 90:
            issues.append(QualityIssue(
                'duplication', 'CRITICAL',
                "检测到连续多日K线数据完全相同，疑似数据源故障未及时更新",
                penalty=(100 - duplication_score) * 0.15
            ))

        # 维度3：时效性
        timeliness_score = self._check_kline_timeliness(klines, period)
        scores['timeliness'] = timeliness_score
        if timeliness_score < 80:
            latest_time = klines[-1]['time'] if klines else 'N/A'
            issues.append(QualityIssue(
                'timeliness', 'WARNING',
                f"最新数据时间{latest_time}，与预期更新时间存在较大延迟",
                penalty=(100 - timeliness_score) * 0.20
            ))

        # 维度4：缺失值
        missing_score = self._check_missing_values(klines, required_fields=['open', 'high', 'low', 'close', 'volume'])
        scores['missing_values'] = missing_score
        if missing_score < 95:
            issues.append(QualityIssue(
                'missing_values', 'WARNING',
                f"关键字段存在缺失值，完整度{missing_score:.0f}%",
                penalty=(100 - missing_score) * 0.15
            ))

        # 维度5：异常值（OHLC逻辑关系 + 涨跌幅合理性）
        outlier_score, outlier_details = self._check_kline_outliers(klines)
        scores['outliers'] = outlier_score
        if outlier_score < 90:
            issues.append(QualityIssue(
                'outliers', 'CRITICAL' if outlier_score < 70 else 'WARNING',
                f"检测到{len(outlier_details)}处异常值：{outlier_details[:3]}",
                penalty=(100 - outlier_score) * 0.15
            ))

        # 维度6：可信度（K线场景下暂不做跨源校验，固定满分；财务数据会用到此维度）
        scores['reliability'] = 100

        overall = sum(scores[k] * self.DIMENSION_WEIGHTS[k] for k in scores)

        return DataQualityResult(
            data_type='kline', stock_code=stock_code,
            overall_score=round(overall, 1), dimension_scores=scores,
            issues=issues, passed=overall >= self.QUALITY_PASS_THRESHOLD,
            checked_at=datetime.utcnow().isoformat()
        )

    def check_quote(self, stock_code: str, quote: dict) -> DataQualityResult:
        """实时报价质量检查（比K线检查更轻量，因为调用频率更高）"""
        issues = []
        scores = {'completeness': 100, 'duplication': 100, 'timeliness': 100,
                  'missing_values': 100, 'outliers': 100, 'reliability': 100}

        if not quote:
            return DataQualityResult(
                'quote', stock_code, 0, scores,
                [QualityIssue('completeness', 'CRITICAL', '报价数据为空', 100)],
                False, datetime.utcnow().isoformat()
            )

        required = ['price', 'open', 'high', 'low', 'prev_close', 'volume']
        missing = [f for f in required if quote.get(f) is None]
        if missing:
            scores['missing_values'] = max(0, 100 - len(missing) * 20)
            issues.append(QualityIssue('missing_values', 'CRITICAL', f"缺失字段：{missing}", len(missing) * 20))

        price = quote.get('price', 0)
        high = quote.get('high', 0)
        low = quote.get('low', 0)
        prev_close = quote.get('prev_close', price)

        if price <= 0:
            scores['outliers'] = 0
            issues.append(QualityIssue('outliers', 'CRITICAL', f"价格异常：{price}", 100))
        elif high < low:
            scores['outliers'] = 0
            issues.append(QualityIssue('outliers', 'CRITICAL', f"最高价{high}小于最低价{low}，逻辑矛盾", 100))
        elif prev_close > 0 and abs(price / prev_close - 1) > 0.22:
            # A股涨跌停一般是10%（ST 5%，新股首日不限），超过22%几乎必然是数据错误
            scores['outliers'] = 20
            issues.append(QualityIssue('outliers', 'CRITICAL',
                                       f"涨跌幅{(price/prev_close-1)*100:.1f}%超出合理范围", 80))

        timestamp = quote.get('time') or quote.get('timestamp')
        if timestamp:
            delay_seconds = self._calc_delay_seconds(timestamp)
            if delay_seconds > 30:
                scores['timeliness'] = max(0, 100 - delay_seconds)
                issues.append(QualityIssue('timeliness', 'WARNING', f"行情延迟{delay_seconds:.0f}秒", delay_seconds * 0.5))

        overall = sum(scores[k] * self.DIMENSION_WEIGHTS[k] for k in scores)
        return DataQualityResult(
            'quote', stock_code, round(overall, 1), scores, issues,
            overall >= self.QUALITY_PASS_THRESHOLD, datetime.utcnow().isoformat()
        )

    def check_financial_report(self, stock_code: str, report: dict) -> DataQualityResult:
        """财务数据质量检查，重点是publish_date合法性（与27文档防未来函数呼应）"""
        issues = []
        scores = {'completeness': 100, 'duplication': 100, 'timeliness': 100,
                  'missing_values': 100, 'outliers': 100, 'reliability': 100}

        if not report:
            return DataQualityResult('financial_report', stock_code, 0, scores,
                                     [QualityIssue('completeness', 'CRITICAL', '财务数据为空', 100)],
                                     False, datetime.utcnow().isoformat())

        # 关键检查：publish_date 不能早于 report_date（与27文档的防未来函数检查呼应，这里是数据入库时的前置防线）
        if report.get('publish_date') and report.get('report_date'):
            if report['publish_date'] < report['report_date']:
                scores['reliability'] = 0
                issues.append(QualityIssue(
                    'reliability', 'CRITICAL',
                    f"发布日期({report['publish_date']})早于报告期({report['report_date']})，数据存在逻辑错误",
                    100
                ))
        elif not report.get('publish_date'):
            scores['reliability'] = 30
            issues.append(QualityIssue(
                'reliability', 'CRITICAL',
                "publish_date字段缺失，存在未来函数风险（27文档要求严格使用publish_date）",
                70
            ))

        key_fields = ['revenue', 'net_profit', 'roe', 'pe_ratio']
        missing = [f for f in key_fields if report.get(f) is None]
        if missing:
            scores['missing_values'] = max(0, 100 - len(missing) * 15)
            issues.append(QualityIssue('missing_values', 'WARNING', f"关键财务字段缺失：{missing}", len(missing) * 15))

        # 异常值：营收/净利润不应为负无穷大的离谱值，ROE超过200%基本是数据错误
        roe = report.get('roe')
        if roe is not None and (roe > 200 or roe < -200):
            scores['outliers'] = 30
            issues.append(QualityIssue('outliers', 'WARNING', f"ROE={roe}%超出合理范围", 70))

        overall = sum(scores[k] * self.DIMENSION_WEIGHTS[k] for k in scores)
        return DataQualityResult(
            'financial_report', stock_code, round(overall, 1), scores, issues,
            overall >= self.QUALITY_PASS_THRESHOLD, datetime.utcnow().isoformat()
        )

    def _check_kline_duplication(self, klines: List[dict]) -> float:
        if len(klines) < 3:
            return 100
        consecutive_identical = 0
        max_consecutive = 0
        for i in range(1, len(klines)):
            prev, curr = klines[i-1], klines[i]
            if (prev['open'] == curr['open'] and prev['high'] == curr['high'] and
                prev['low'] == curr['low'] and prev['close'] == curr['close']):
                consecutive_identical += 1
                max_consecutive = max(max_consecutive, consecutive_identical)
            else:
                consecutive_identical = 0
        if max_consecutive >= 3:
            return max(0, 100 - max_consecutive * 25)
        return 100

    def _check_kline_timeliness(self, klines: List[dict], period: str) -> float:
        if not klines:
            return 0
        latest = klines[-1]
        latest_time = pd.Timestamp(latest['time'])
        now = pd.Timestamp.now(tz=latest_time.tz)

        # 不同周期的合理延迟容忍度不同
        max_delay_map = {'1min': timedelta(minutes=5), '5min': timedelta(minutes=15),
                         '60min': timedelta(hours=2), '1d': timedelta(days=2)}
        max_delay = max_delay_map.get(period, timedelta(days=2))

        actual_delay = now - latest_time
        if actual_delay <= max_delay:
            return 100
        excess_ratio = (actual_delay - max_delay) / max_delay
        return max(0, 100 - excess_ratio * 50)

    def _check_missing_values(self, klines: List[dict], required_fields: List[str]) -> float:
        if not klines:
            return 0
        total_fields = len(klines) * len(required_fields)
        missing_count = sum(
            1 for k in klines for f in required_fields
            if k.get(f) is None
        )
        return max(0, 100 - missing_count / total_fields * 100) if total_fields > 0 else 100

    def _check_kline_outliers(self, klines: List[dict]) -> tuple:
        issues = []
        for i, k in enumerate(klines):
            if k['high'] < k['low']:
                issues.append(f"第{i}条：最高价<最低价")
            if k['close'] > k['high'] * 1.001 or k['close'] < k['low'] * 0.999:
                issues.append(f"第{i}条：收盘价超出当日高低范围")
            if k['volume'] < 0 or k['amount'] < 0:
                issues.append(f"第{i}条：成交量/额为负数")
            if i > 0:
                prev_close = klines[i-1]['close']
                if prev_close > 0:
                    change = abs(k['close'] / prev_close - 1)
                    if change > 0.22:  # 非新股不应超过22%（含极端情况缓冲）
                        issues.append(f"第{i}条：涨跌幅{change*100:.1f}%异常")
        score = max(0, 100 - len(issues) * 10)
        return score, issues

    def _calc_delay_seconds(self, timestamp) -> float:
        ts = pd.Timestamp(timestamp)
        now = pd.Timestamp.now(tz=ts.tz if ts.tz else None)
        return max(0, (now - ts).total_seconds())
```

### 3.2 质量门禁（拦截低质量数据）

```python
# backend/app/data_quality/gate.py

import structlog
logger = structlog.get_logger()

class QualityGate:
    """
    集成到 DataService.get_full_context() 调用链中
    质量不达标时返回明确的拒绝原因，而不是继续往下传递错误数据
    """

    def __init__(self, checker, db):
        self.checker = checker
        self.db = db

    async def validate_before_analysis(self, stock_code: str, context: dict) -> dict:
        """
        在 AgentOrchestrator.analyze() 调用前执行
        返回 {passed: bool, score: float, blocking_issues: list, context: dict}
        """
        results = []

        if context.get('kline_1d'):
            kline_result = self.checker.check_kline(
                stock_code, context['kline_1d'], '1d', expected_count=60
            )
            results.append(kline_result)

        if context.get('price'):
            quote_result = self.checker.check_quote(stock_code, {
                'price': context.get('price'), 'open': context.get('open'),
                'high': context.get('high'), 'low': context.get('low'),
                'prev_close': context.get('prev_close'), 'volume': context.get('volume'),
            })
            results.append(quote_result)

        if context.get('financial_report'):
            financial_result = self.checker.check_financial_report(
                stock_code, context['financial_report']
            )
            results.append(financial_result)

        if not results:
            return {'passed': False, 'score': 0, 'blocking_issues': ['无可用数据'], 'results': []}

        overall_score = sum(r.overall_score for r in results) / len(results)
        critical_issues = [
            issue.description for r in results for issue in r.issues
            if issue.severity == 'CRITICAL'
        ]

        passed = overall_score >= self.checker.QUALITY_PASS_THRESHOLD and not critical_issues

        await self._log_quality_check(stock_code, overall_score, results, passed)

        if not passed:
            logger.warning("data_quality_gate_blocked",
                          code=stock_code, score=overall_score, issues=critical_issues)

        return {
            'passed': passed,
            'score': round(overall_score, 1),
            'blocking_issues': critical_issues,
            'results': results,
        }

    async def _log_quality_check(self, stock_code, score, results, passed):
        await self.db.execute("""
            INSERT INTO data_quality.check_logs
            (stock_code, overall_score, passed, dimension_breakdown, issues)
            VALUES ($1, $2, $3, $4, $5)
        """, stock_code, score, passed,
             {r.data_type: r.dimension_scores for r in results},
             [{'type': r.data_type, 'issues': [i.__dict__ for i in r.issues]} for r in results])
```

## 4. 系统架构

```
DataService.get_full_context(code)
            │
            ▼
   （原有数据获取流程不变，见10_14文档）
            │
            ▼
┌───────────────────────┐
│   QualityGate.validate │  ← 新增环节，插入在数据获取完成后、传给AI之前
│   _before_analysis()   │
└───────────┬───────────┘
            │
    ┌───────┴───────┐
    ▼               ▼
 passed=True    passed=False
    │               │
    ▼               ▼
AgentOrchestrator  拒绝分析，返回
   .analyze()      明确原因给调用方
                   （API层捕获并返回
                    "数据质量不足，暂无法分析"）

并行：
QualityMonitor（独立定时任务）
            │
            ▼
扫描数据库中近期数据，发现渐进式质量劣化
（如某只股票连续多日资金流向数据缺失）
            │
            ▼
写入 data_quality.degradation_alerts
推送WebSocket告警（不阻断，因为是历史数据巡检不是实时拦截）
```

## 5. 数据流

```
1. AIService.analyze(code) 被调用（API层或Celery定时任务）
2. DataService.get_full_context(code) 按原有逻辑获取所有数据（10_14文档不变）
3. 新增步骤：QualityGate.validate_before_analysis(code, context)
4. 若 passed=False：
   a. 记录到 data_quality.check_logs
   b. AIService 直接返回错误响应，不调用 AgentOrchestrator（节省AI调用成本，避免基于垃圾数据生成信号）
   c. 若是Celery定时扫描场景（run_signal_scan），静默跳过该股票，记录日志，继续下一只
5. 若 passed=True：
   a. 记录质量分数到 ai.signals 表的新增字段 data_quality_score（供事后审计："这个信号是基于多高质量的数据生成的"）
   b. 正常进入 AgentOrchestrator.analyze() 流程
6. QualityMonitor 每日凌晨独立运行，扫描近7天所有有交易信号的股票的数据完整性趋势
7. 发现连续3天质量评分低于85分的股票，写入degradation_alerts并推送告警
```

## 6. 数据库设计（新增数据表）

```sql
CREATE SCHEMA IF NOT EXISTS data_quality;

-- 质量检查日志（每次AI分析前的质量门禁检查都记录）
CREATE TABLE data_quality.check_logs (
    id                  BIGSERIAL       PRIMARY KEY,
    stock_code          VARCHAR(10)     NOT NULL,
    overall_score       NUMERIC(5,2)    NOT NULL,
    passed              BOOLEAN         NOT NULL,
    dimension_breakdown JSONB,                       -- 各数据类型的六维度得分
    issues              JSONB,                        -- 完整问题列表
    checked_at          TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX idx_quality_logs_stock_time ON data_quality.check_logs(stock_code, checked_at DESC);
CREATE INDEX idx_quality_logs_passed ON data_quality.check_logs(passed) WHERE passed = FALSE;

-- 质量劣化告警（QualityMonitor巡检产出）
CREATE TABLE data_quality.degradation_alerts (
    id                  BIGSERIAL       PRIMARY KEY,
    stock_code          VARCHAR(10)     NOT NULL,
    data_type           VARCHAR(30)     NOT NULL,     -- kline/quote/financial_report/fund_flow/news
    consecutive_days     INT             NOT NULL,
    avg_score             NUMERIC(5,2)    NOT NULL,
    detail                JSONB,
    is_resolved            BOOLEAN         DEFAULT FALSE,
    detected_at            TIMESTAMPTZ     DEFAULT NOW(),
    resolved_at            TIMESTAMPTZ
);

-- 扩展 ai.signals 表（15_16文档中已定义），新增数据质量关联字段
ALTER TABLE ai.signals
    ADD COLUMN data_quality_score NUMERIC(5,2);   -- 该信号生成时所用数据的质量分数，供事后审计
```

## 7. API设计

```
GET  /api/v1/data-quality/{code}/score
     查询股票当前各类数据的质量评分

GET  /api/v1/data-quality/check-logs?passed=false&days=7
     近期未通过质量门禁的检查记录（排查问题用）

GET  /api/v1/data-quality/degradation-alerts
     当前未解决的质量劣化告警列表

POST /api/v1/data-quality/degradation-alerts/{id}/resolve
     人工标记告警已处理（如确认是上游数据源临时问题，已联系修复）

GET  /api/v1/data-quality/dashboard-summary
     质量总览：今日检查总数/通过率/各数据类型平均分（供前端Dashboard展示）
```

## 8. AI Agent职责

**本模块不新增独立的LLM Agent**，质量评分是确定性规则计算，理由与53文档的晋级判定相同：质量门禁是资金安全相关的客观判断，不应引入LLM的主观性和不确定性。

但有一个轻量级集成：在`FundamentalAgent`（15_16文档已存在）的Prompt中，应当注入数据质量评分作为上下文，让Agent在分析时知晓数据可信度，从而在`confidence`字段中体现这种不确定性：

```python
# 对 15_16文档 BaseAgent._build_market_context_str() 的微调
def _build_market_context_str(self, context: dict) -> str:
    quality_note = ""
    if context.get('data_quality_score') is not None and context['data_quality_score'] < 90:
        quality_note = f"\n注意：本次数据质量评分为{context['data_quality_score']}/100，存在一定不确定性，请在分析中适当保守。\n"
    return quality_note + f"""股票代码：{context.get('code')}  ..."""
```

## 9. 前端页面设计

新增 **数据质量** 子页面，挂载方式：在"风控中心"页面新增第4个Tab（与52文档的"组合健康"Tab并列），保持现有菜单结构不扩张：

```
风控中心
├── Tab 1: 风控规则
├── Tab 2: 熔断记录
├── Tab 3: 组合健康（52文档新增）
└── Tab 4: 数据质量（本文档新增）
    ├── 今日质量总览（通过率/平均分/各数据类型对比柱状图）
    ├── 未通过检查列表（可筛选股票/时间范围）
    ├── 质量劣化告警列表（红色高亮未解决项）
    └── 单股票质量趋势图（折线图，近30天质量分数变化）
```

在 **AI决策页**（42_44文档已存在）的分析结果展示中，新增质量分数标签：

```
若 data_quality_score < 80，在 SignalSummary 组件顶部显示醒目警告条：
"⚠️ 本次分析基于的数据质量评分为72/100，建议谨慎参考此信号"
```

## 10. 定时任务

```python
# 新增到 worker/celery_app.py 的 beat_schedule

'data-quality-degradation-scan': {
    'task': 'tasks.scan_data_quality_degradation',
    'schedule': crontab(hour=6, minute=0),   # 每日开盘前扫描（早于9:15的选股任务）
},
'data-quality-cleanup-old-logs': {
    'task': 'tasks.cleanup_old_quality_logs',
    'schedule': crontab(day_of_week=0, hour=3, minute=30),  # 每周清理90天前的检查日志
},
```

```python
# worker/tasks/data_quality.py

@shared_task(name='tasks.scan_data_quality_degradation', queue='low')
def scan_data_quality_degradation():
    """扫描近7天有交易活动的股票，识别连续质量劣化"""
    import asyncio
    from app.data_quality.checker import DataQualityChecker

    async def _run():
        from app.db import get_db
        async with get_db() as db:
            stocks = await db.fetch("""
                SELECT DISTINCT stock_code FROM ai.signals
                WHERE created_at > NOW() - INTERVAL '7 days'
            """)

            for s in stocks:
                code = s['stock_code']
                recent_scores = await db.fetch("""
                    SELECT overall_score, checked_at FROM data_quality.check_logs
                    WHERE stock_code = $1 AND checked_at > NOW() - INTERVAL '3 days'
                    ORDER BY checked_at DESC
                """, code)

                if len(recent_scores) >= 3 and all(r['overall_score'] < 85 for r in recent_scores[:3]):
                    avg_score = sum(r['overall_score'] for r in recent_scores[:3]) / 3
                    existing = await db.fetchval("""
                        SELECT id FROM data_quality.degradation_alerts
                        WHERE stock_code = $1 AND is_resolved = FALSE
                    """, code)
                    if not existing:
                        await db.execute("""
                            INSERT INTO data_quality.degradation_alerts
                            (stock_code, data_type, consecutive_days, avg_score)
                            VALUES ($1, 'mixed', 3, $2)
                        """, code, avg_score)

    asyncio.run(_run())
```

## 11. 配置项

```env
# ── 数据质量中心 ──
DATA_QUALITY_PASS_THRESHOLD=80           # 质量门禁通过阈值
DATA_QUALITY_KLINE_MAX_DELAY_DAYS=2      # 日线数据最大可接受延迟天数
DATA_QUALITY_QUOTE_MAX_DELAY_SECONDS=30  # 实时报价最大可接受延迟秒数
DATA_QUALITY_GATE_ENABLED=true           # 是否启用质量门禁拦截（建议生产环境始终true）
DATA_QUALITY_LOG_RETENTION_DAYS=90       # 质量检查日志保留天数
```

## 12. 开发优先级

属于 **Phase 1（MVP）末尾或Phase 2（AI核心）开头**，建议在`03_DEVELOPMENT_ROADMAP.md`中插入到Phase 2任务清单的最前面，**先于4个Agent的开发**。理由：质量门禁是AI分析链路的前置环节，如果先开发完Agent再补质量检查，意味着Phase 2开发和测试期间所有Agent的调试都是在未经质量校验的数据上进行的，容易把"数据问题"误判为"Agent逻辑问题"，浪费调试时间。

这是文档中标记为**P0必须**的第三个新增模块，与51（市场状态）、53（策略生命周期）一起构成系统的三道前置安全闸门：51回答"现在适不适合交易"，53回答"这个策略允不允许用钱"，54回答"这批数据能不能信"。三者均为**阻断式**而非建议式的设计，这是真实资金系统的必要保守性。

## 13. 验收标准（Definition of Done）

```
□ DataQualityChecker.check_kline() 能正确识别"连续3天OHLC完全相同"的故障数据，扣分到CRITICAL级别
□ DataQualityChecker.check_financial_report() 能拦截 publish_date < report_date 的逻辑错误数据
□ QualityGate.validate_before_analysis() 在 passed=False 时，AgentOrchestrator.analyze() 确实不会被调用（用mock验证AI API无调用记录）
□ 质量评分计算耗时 < 200ms（不能成为AI分析延迟的主要瓶颈）
□ data_quality_score 正确写入 ai.signals 表，可在前端SignalSummary中查看
□ QualityMonitor 每日扫描任务运行时间 < 5分钟（全市场5000只股票规模下）
□ 质量劣化告警的去重逻辑正确（同一股票未解决的告警不会重复创建）
□ 前端"数据质量"Tab正确展示通过率趋势图，且能筛选特定股票查看历史
```

## 14. 与现有系统如何集成

**集成点1（核心）：`10_14_DATA_PIPELINE.md`的`DataService.get_full_context()`方法需要在返回前调用质量检查，并将结果附加到返回的context中：**

```python
# 对 10_14文档 DataService.get_full_context() 的修改
async def get_full_context(self, code: str) -> dict:
    # ... 原有的并发数据获取逻辑完全不变 ...

    context = {
        'code': code, 'name': stock_info.get('name', code),
        # ... 原有所有字段 ...
    }

    # 新增：质量检查（注意是在数据组装完成后，返回前的最后一步）
    from app.data_quality.gate import QualityGate
    from app.data_quality.checker import DataQualityChecker
    gate = QualityGate(DataQualityChecker(), self.db)
    quality_result = await gate.validate_before_analysis(code, context)
    context['_quality_check'] = quality_result
    context['data_quality_score'] = quality_result['score']

    return context
```

**集成点2：`15_16_AI_ARCHITECTURE_AGENTS.md`的`AgentOrchestrator.analyze()`方法入口处新增门禁检查：**

```python
# 对 15_16文档 AgentOrchestrator.analyze() 的修改
async def analyze(self, stock_code: str, context: dict) -> dict:
    # 新增：质量门禁检查（在原有4个Agent并发执行之前）
    quality_check = context.get('_quality_check', {})
    if not quality_check.get('passed', True):  # 默认True避免context未经过质量检查时误拦截
        return {
            'id': str(uuid.uuid4()), 'stock_code': stock_code,
            'action': 'HOLD', 'confidence': 0.0, 'risk_level': 'EXTREME',
            'reason': f"数据质量不达标（评分{quality_check.get('score')}），拒绝生成交易信号。"
                     f"问题：{'; '.join(quality_check.get('blocking_issues', []))}",
            'signal_time': datetime.utcnow().isoformat(),
            '_blocked_by_quality_gate': True,
        }

    # 原有4个Agent并发分析逻辑不变...
```

**集成点3：`39_41_API_WEBSOCKET.md`的`run_signal_scan`任务（Celery定时任务）需要静默跳过质量不达标的股票，而非报错中断整个批量扫描：**

```python
# 对 39_41文档 run_signal_scan 任务的微调（在原有for循环内）
for code in codes[:20]:
    try:
        context = await svc.get_full_context(code)
        if not context.get('price'):
            continue

        # 新增：质量门禁前置过滤，节省AI调用成本
        if not context.get('_quality_check', {}).get('passed', True):
            logger.info("signal_scan_skipped_low_quality", code=code,
                       score=context.get('data_quality_score'))
            continue

        signal = await orchestrator.analyze(code, context)
        # ... 原有逻辑不变
```

**不需要修改的部分：** `DataClient`（HTTP请求封装）完全不变，质量检查是在数据已经成功获取后才介入；`CacheManager`的TTL策略不变；`06_INFRA_DATABASE.md`中现有表结构除`ai.signals`新增一个字段外均不变。
