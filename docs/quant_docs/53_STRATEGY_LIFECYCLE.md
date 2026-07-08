# 53 — 策略生命周期与晋级机制（Strategy Lifecycle & Promotion）

> 优先级：**P0 必须**。这是真实资金系统最重要的安全闸门之一：任何策略（无论人工设计还是AI生成）都不能跳过阶段直接进入实盘。

---

## 1. 为什么需要新增

`21_STRATEGY_FACTORY.md`定义了策略"怎么写"（StrategyFactory + BaseStrategy），`03_DEVELOPMENT_ROADMAP.md`定义了整个**项目**的5阶段路线图（MVP→AI核心→自动化→回测→实盘）。但这两份文档都没有回答一个关键问题："**单个策略实例**从被创建到被允许使用真实资金，要经历哪些状态，每个状态切换的条件是什么？"

`03文档`的Phase 5验收标准提到"纸盘运行满90天"，这是**项目级**的门禁（整个系统能不能开实盘开关）。但当系统已经进入实盘阶段后，新增的第N个策略（比如运营半年后新设计的一个动量策略）该如何获准上线？现有文档没有覆盖这个持续性问题——实盘系统不会只用一套策略，会持续迭代，每个新策略都需要独立走完验证流程，不能因为"系统已经在实盘了"就跳过验证直接上线新策略。

这正是用户特别强调的红线：**"AI可以提出策略候选，但任何新策略都必须经过Backtest→Walk Forward→Paper Trading→Risk Validation，达到晋级标准后才能进入Production，禁止AI自动生成策略后直接进入正式交易。"**

## 2. 设计目标

```
1. 为每个策略实例（不是策略类型，是配置后的具体策略）定义清晰的状态机
2. 每个状态转换都有明确的、可量化的晋级条件和自动降级条件
3. 状态转换必须留痕（审计），人工干预必须记录operator
4. 与现有 21_STRATEGY_FACTORY.md 的 strategy.strategies 表集成，新增状态管理字段
5. 与现有 28_29_WALKFORWARD_AUTOML.md 的验证结果直接挂钩晋级判定
```

## 3. 核心功能

```
StrategyLifecycleManager：状态机引擎，管理状态转换的合法性校验
PromotionEvaluator：自动评估策略是否满足晋级条件
DemotionMonitor：持续监控已晋级策略的实盘/纸盘表现，触发自动降级
LifecycleAuditLog：所有状态变更的完整记录
```

### 3.1 状态机定义

```python
# backend/app/strategy/lifecycle.py

from enum import Enum
from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime

class StrategyStage(str, Enum):
    DRAFT = "DRAFT"                    # 草稿：刚创建，未经任何验证
    BACKTEST = "BACKTEST"              # 回测中：正在跑普通回测
    WALK_FORWARD = "WALK_FORWARD"      # Walk-Forward验证中
    PAPER_TRADING = "PAPER_TRADING"    # 纸盘运行中
    TRIAL = "TRIAL"                    # 小资金实盘试运行
    PRODUCTION = "PRODUCTION"          # 正式生产（完整资金额度）
    DEPRECATED = "DEPRECATED"          # 已弃用（表现下滑，暂停使用但保留记录）
    ARCHIVED = "ARCHIVED"              # 已归档（永久停用）

# 合法的状态转换图（防止跳级）
ALLOWED_TRANSITIONS = {
    StrategyStage.DRAFT:          [StrategyStage.BACKTEST, StrategyStage.ARCHIVED],
    StrategyStage.BACKTEST:       [StrategyStage.WALK_FORWARD, StrategyStage.DRAFT, StrategyStage.ARCHIVED],
    StrategyStage.WALK_FORWARD:   [StrategyStage.PAPER_TRADING, StrategyStage.BACKTEST, StrategyStage.ARCHIVED],
    StrategyStage.PAPER_TRADING:  [StrategyStage.TRIAL, StrategyStage.WALK_FORWARD, StrategyStage.DEPRECATED],
    StrategyStage.TRIAL:          [StrategyStage.PRODUCTION, StrategyStage.PAPER_TRADING, StrategyStage.DEPRECATED],
    StrategyStage.PRODUCTION:     [StrategyStage.DEPRECATED],   # 生产状态只能降级，不能跳回任何阶段
    StrategyStage.DEPRECATED:     [StrategyStage.PAPER_TRADING, StrategyStage.ARCHIVED],  # 允许重新验证后复活
    StrategyStage.ARCHIVED:       [],  # 终态，不可逆
}

@dataclass
class PromotionCriteria:
    """每个阶段的晋级条件（量化、可自动判定）"""
    stage: StrategyStage
    min_duration_days: int
    conditions: dict
    description: str

# 晋级条件定义（核心配置，必须严格遵守，不允许代码绕过）
PROMOTION_RULES = {
    StrategyStage.BACKTEST: PromotionCriteria(
        stage=StrategyStage.WALK_FORWARD,
        min_duration_days=0,    # 回测本身不要求最短时长，但要求结果达标
        conditions={
            'min_sharpe_ratio': 1.0,
            'max_drawdown_pct': -20.0,         # 回测最大回撤不能超过20%
            'min_total_trades': 30,             # 样本量太少不可信
            'lookahead_check_passed': True,     # 必须通过27文档的LookaheadChecker
        },
        description="普通回测：夏普≥1.0，最大回撤≤20%，至少30笔交易，且通过防未来函数检查"
    ),
    StrategyStage.WALK_FORWARD: PromotionCriteria(
        stage=StrategyStage.PAPER_TRADING,
        min_duration_days=0,
        conditions={
            'oos_win_rate': 0.60,               # 样本外胜率≥60%（对应28_29文档的is_robust判定）
            'oos_avg_sharpe': 0.8,
            'param_stability_score': 0.65,
            'overfit_level_not': ['HIGH'],       # 过拟合检测不能是HIGH级别
        },
        description="Walk-Forward验证：样本外窗口胜率≥60%，平均夏普≥0.8，参数稳定性≥0.65，且过拟合等级非HIGH"
    ),
    StrategyStage.PAPER_TRADING: PromotionCriteria(
        stage=StrategyStage.TRIAL,
        min_duration_days=90,     # 硬性要求：纸盘至少跑满90天（对齐03文档Phase 5前提条件）
        conditions={
            'min_trading_days': 60,             # 至少60个真实交易日有信号触发（防止长期无交易的空转策略蒙混过关）
            'annual_return_vs_benchmark': 0.0,   # 纸盘收益至少不低于基准（沪深300）
            'max_drawdown_pct': -12.0,           # 纸盘实际回撤必须低于熔断线15%，留出3%安全边际
            'sharpe_ratio': 0.8,
            'no_critical_bugs': True,            # 期间无因策略逻辑bug导致的异常交易
        },
        description="纸盘交易：连续运行≥90天，≥60个有效交易日，年化跑赢基准，最大回撤≤12%，夏普≥0.8，无重大bug"
    ),
    StrategyStage.TRIAL: PromotionCriteria(
        stage=StrategyStage.PRODUCTION,
        min_duration_days=30,     # 小资金实盘至少30天
        conditions={
            'capital_allocated_max': 0.05,       # 试运行阶段资金占比不超过总资金5%（配置约束，非结果约束）
            'live_vs_paper_deviation': 0.15,     # 实盘表现与纸盘预期偏差不超过15%（检测滑点/执行差异是否过大）
            'reconciliation_clean_days': 30,     # 30天对账无异常（依赖35_38文档的对账机制）
            'no_risk_events_critical': True,     # 期间无CRITICAL级别风控事件
        },
        description="小资金试运行：≥30天，资金占比≤5%，实盘与纸盘偏差≤15%，对账连续无误，无重大风控事件"
    ),
}

# 自动降级条件（持续监控，不需要等待固定周期，触发即降级）
DEMOTION_TRIGGERS = {
    StrategyStage.PRODUCTION: {
        'consecutive_loss_days': 10,         # 连续10个交易日亏损
        'drawdown_breach_pct': -15.0,        # 触及31_34文档的熔断线
        'sharpe_below': 0.3,                 # 滚动30日夏普跌破0.3
        'action': StrategyStage.DEPRECATED,
    },
    StrategyStage.TRIAL: {
        'consecutive_loss_days': 7,
        'drawdown_breach_pct': -10.0,
        'action': StrategyStage.PAPER_TRADING,   # 试运行表现不佳，打回纸盘重新观察
    },
}
```

### 3.2 晋级评估器

```python
# backend/app/strategy/promotion_evaluator.py

from .lifecycle import PROMOTION_RULES, StrategyStage, ALLOWED_TRANSITIONS
from datetime import datetime

class PromotionEvaluator:
    """
    评估策略是否满足晋级条件
    所有判定逻辑必须是确定性的（基于数据库查询的量化指标），不引入LLM主观判断
    晋级决策的客观性是资金安全的关键保障
    """

    def __init__(self, db):
        self.db = db

    async def evaluate(self, strategy_id: int) -> dict:
        strategy = await self._get_strategy(strategy_id)
        current_stage = StrategyStage(strategy['lifecycle_stage'])

        if current_stage not in PROMOTION_RULES:
            return {
                'eligible': False,
                'reason': f"{current_stage.value} 阶段无定义的晋级路径（可能已是终态或需人工评估）"
            }

        criteria = PROMOTION_RULES[current_stage]
        stage_entered_at = strategy['stage_entered_at']
        duration_days = (datetime.utcnow() - stage_entered_at).days

        # 第一道检查：最短停留时长（硬性，不可绕过）
        if duration_days < criteria.min_duration_days:
            return {
                'eligible': False,
                'reason': f"当前阶段仅运行{duration_days}天，未满最低要求{criteria.min_duration_days}天",
                'days_remaining': criteria.min_duration_days - duration_days,
            }

        # 第二道检查：量化条件逐项核验
        actual_metrics = await self._gather_metrics(strategy_id, current_stage)
        failed_conditions = []

        for condition_key, required_value in criteria.conditions.items():
            actual_value = actual_metrics.get(condition_key)
            if not self._check_condition(condition_key, actual_value, required_value):
                failed_conditions.append({
                    'condition': condition_key,
                    'required': required_value,
                    'actual': actual_value,
                })

        eligible = len(failed_conditions) == 0

        result = {
            'eligible': eligible,
            'current_stage': current_stage.value,
            'target_stage': criteria.stage.value,
            'duration_days': duration_days,
            'actual_metrics': actual_metrics,
            'failed_conditions': failed_conditions,
            'description': criteria.description,
        }

        # 记录评估历史（即使不通过也要记录，便于追溯策略改进过程）
        await self._log_evaluation(strategy_id, result)

        return result

    def _check_condition(self, key: str, actual, required) -> bool:
        if actual is None:
            return False
        if key.startswith('max_') or key.endswith('_breach_pct'):
            return actual >= required  # 最大回撤类指标是负数，actual应不低于阈值（即回撤没那么深）
        if key.startswith('min_'):
            return actual >= required
        if key == 'overfit_level_not':
            return actual not in required
        if key in ('lookahead_check_passed', 'no_critical_bugs', 'no_risk_events_critical'):
            return actual == required
        if key == 'capital_allocated_max':
            return actual <= required
        if key == 'live_vs_paper_deviation':
            return abs(actual) <= required
        # 默认：数值类条件要求 actual >= required
        return actual >= required

    async def _gather_metrics(self, strategy_id: int, stage: StrategyStage) -> dict:
        """
        从不同来源聚合指标：
        - BACKTEST阶段：从 backtest.results 表读取（28_29文档）
        - WALK_FORWARD阶段：从 backtest.results 表读取walk_forward相关字段
        - PAPER_TRADING阶段：从 trade.account_records (mode='paper') 聚合计算
        - TRIAL阶段：从 trade.account_records (mode='live') + reconciliation记录聚合
        """
        if stage == StrategyStage.BACKTEST:
            return await self._gather_backtest_metrics(strategy_id)
        elif stage == StrategyStage.WALK_FORWARD:
            return await self._gather_walkforward_metrics(strategy_id)
        elif stage == StrategyStage.PAPER_TRADING:
            return await self._gather_paper_metrics(strategy_id)
        elif stage == StrategyStage.TRIAL:
            return await self._gather_trial_metrics(strategy_id)
        return {}

    async def _gather_backtest_metrics(self, strategy_id: int) -> dict:
        row = await self.db.fetchone("""
            SELECT sharpe_ratio, max_drawdown, total_trades
            FROM backtest.results br
            JOIN backtest.tasks bt ON br.task_id = bt.id
            WHERE bt.strategy_id = $1
            ORDER BY br.created_at DESC LIMIT 1
        """, strategy_id)
        task = await self.db.fetchone("""
            SELECT lookahead_checked, lookahead_issues
            FROM backtest.tasks WHERE strategy_id = $1
            ORDER BY created_at DESC LIMIT 1
        """, strategy_id)

        lookahead_passed = (
            task and task['lookahead_checked'] and
            not any(i.get('severity') == 'ERROR' for i in (task['lookahead_issues'] or []))
        )

        return {
            'min_sharpe_ratio': row['sharpe_ratio'] if row else None,
            'max_drawdown_pct': row['max_drawdown'] if row else None,
            'min_total_trades': row['total_trades'] if row else None,
            'lookahead_check_passed': lookahead_passed,
        }

    async def _gather_walkforward_metrics(self, strategy_id: int) -> dict:
        row = await self.db.fetchone("""
            SELECT oos_return, oos_sharpe
            FROM backtest.results br
            JOIN backtest.tasks bt ON br.task_id = bt.id
            WHERE bt.strategy_id = $1 AND br.walk_forward_period IS NOT NULL
            ORDER BY br.created_at DESC
        """, strategy_id)
        # 实际实现需要聚合所有walk-forward窗口结果，计算win_rate等
        # 此处简化展示核心思路，完整实现见28_29文档WalkForwardRunner._aggregate_oos_results
        return {
            'oos_win_rate': None,        # 由聚合逻辑填充
            'oos_avg_sharpe': None,
            'param_stability_score': None,
            'overfit_level_not': None,
        }

    async def _gather_paper_metrics(self, strategy_id: int) -> dict:
        # 从 trade.account_records (mode='paper') 计算纸盘期间表现
        # 需要关联 strategy_id 到具体订单（trade.orders.strategy_id）
        records = await self.db.fetch("""
            SELECT * FROM trade.account_records
            WHERE mode = 'paper' AND record_time >= (
                SELECT stage_entered_at FROM strategy.strategies WHERE id = $1
            )
            ORDER BY record_time
        """, strategy_id)
        trading_days = await self.db.fetchval("""
            SELECT COUNT(DISTINCT DATE(created_at)) FROM trade.orders
            WHERE strategy_id = $1 AND mode = 'paper' AND status = 'FILLED'
        """, strategy_id)

        if not records or len(records) < 2:
            return {'min_trading_days': trading_days or 0}

        # 计算年化收益/最大回撤/夏普（复用28_29文档MetricsCalculator）
        from app.backtest.metrics import MetricsCalculator
        import pandas as pd
        equity = pd.Series(
            [r['total_assets'] for r in records],
            index=[r['record_time'] for r in records]
        )
        calc = MetricsCalculator()
        return {
            'min_trading_days': trading_days or 0,
            'annual_return_vs_benchmark': calc.annual_return(equity),  # 需另行减去基准收益率
            'max_drawdown_pct': calc.max_drawdown(equity),
            'sharpe_ratio': calc.sharpe_ratio(equity.pct_change().dropna()),
            'no_critical_bugs': await self._check_no_critical_bugs(strategy_id, 'paper'),
        }

    async def _gather_trial_metrics(self, strategy_id: int) -> dict:
        # 类似_gather_paper_metrics，但数据源是mode='live'，且额外检查对账记录
        clean_days = await self.db.fetchval("""
            SELECT COUNT(*) FROM (
                SELECT DATE(reconciled_at) as d
                FROM trade.reconciliation_logs
                WHERE strategy_id = $1 AND issues_found = 0
                GROUP BY DATE(reconciled_at)
            ) t
        """, strategy_id) if await self._table_exists('trade.reconciliation_logs') else 0

        return {
            'capital_allocated_max': await self._get_capital_allocation_ratio(strategy_id),
            'live_vs_paper_deviation': await self._calc_live_vs_paper_deviation(strategy_id),
            'reconciliation_clean_days': clean_days,
            'no_risk_events_critical': await self._check_no_critical_risk_events(strategy_id),
        }

    async def _check_no_critical_bugs(self, strategy_id, mode) -> bool:
        count = await self.db.fetchval("""
            SELECT COUNT(*) FROM audit.operation_logs
            WHERE entity_type = 'strategy_bug' AND entity_id = $1::text
        """, strategy_id)
        return count == 0

    async def _check_no_critical_risk_events(self, strategy_id) -> bool:
        count = await self.db.fetchval("""
            SELECT COUNT(*) FROM risk.risk_events re
            JOIN trade.orders o ON re.order_id = o.id
            WHERE o.strategy_id = $1 AND re.detail->>'severity' = 'CRITICAL'
        """, strategy_id)
        return count == 0

    async def _get_strategy(self, strategy_id): ...
    async def _log_evaluation(self, strategy_id, result): ...
    async def _table_exists(self, table_name): ...
    async def _get_capital_allocation_ratio(self, strategy_id): ...
    async def _calc_live_vs_paper_deviation(self, strategy_id): ...
```

### 3.3 状态机管理器（转换执行 + 合法性校验）

```python
# backend/app/strategy/lifecycle_manager.py

from .lifecycle import ALLOWED_TRANSITIONS, StrategyStage, DEMOTION_TRIGGERS

class StrategyLifecycleManager:
    """
    状态转换的唯一入口，所有状态变更必须通过此类执行
    严禁直接UPDATE strategy.strategies表的lifecycle_stage字段
    """

    def __init__(self, db, ws_manager):
        self.db = db
        self.ws = ws_manager

    async def transition(
        self,
        strategy_id: int,
        target_stage: StrategyStage,
        operator: str,
        reason: str,
        force: bool = False,    # 仅允许人工紧急降级时使用，自动晋级流程不可使用force
    ) -> dict:
        strategy = await self._get_strategy(strategy_id)
        current_stage = StrategyStage(strategy['lifecycle_stage'])

        # 校验1：转换路径合法性
        if not force and target_stage not in ALLOWED_TRANSITIONS.get(current_stage, []):
            return {
                'success': False,
                'message': f"不允许从 {current_stage.value} 直接跳转到 {target_stage.value}，"
                           f"合法路径为：{[s.value for s in ALLOWED_TRANSITIONS.get(current_stage, [])]}"
            }

        # 校验2：升级类转换必须经过PromotionEvaluator核验（核心红线，不可绕过）
        is_promotion = self._is_promotion(current_stage, target_stage)
        if is_promotion and not force:
            from .promotion_evaluator import PromotionEvaluator
            evaluator = PromotionEvaluator(self.db)
            eval_result = await evaluator.evaluate(strategy_id)
            if not eval_result['eligible']:
                return {
                    'success': False,
                    'message': f"未满足晋级条件，无法从 {current_stage.value} 晋级到 {target_stage.value}",
                    'failed_conditions': eval_result['failed_conditions'],
                }

        # 执行状态转换（事务）
        with self.db.begin():
            await self.db.execute("""
                UPDATE strategy.strategies
                SET lifecycle_stage = $1, stage_entered_at = NOW(), updated_at = NOW()
                WHERE id = $2
            """, target_stage.value, strategy_id)

            await self.db.execute("""
                INSERT INTO strategy.lifecycle_audit_log
                (strategy_id, from_stage, to_stage, operator, reason, is_promotion, was_forced)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """, strategy_id, current_stage.value, target_stage.value,
                 operator, reason, is_promotion, force)

        await self.ws.broadcast('alerts', {
            'type': 'strategy_lifecycle_change',
            'strategy_id': strategy_id,
            'from_stage': current_stage.value,
            'to_stage': target_stage.value,
            'is_promotion': is_promotion,
        })

        return {'success': True, 'from_stage': current_stage.value, 'to_stage': target_stage.value}

    def _is_promotion(self, current: StrategyStage, target: StrategyStage) -> bool:
        stage_order = [
            StrategyStage.DRAFT, StrategyStage.BACKTEST, StrategyStage.WALK_FORWARD,
            StrategyStage.PAPER_TRADING, StrategyStage.TRIAL, StrategyStage.PRODUCTION
        ]
        try:
            return stage_order.index(target) > stage_order.index(current)
        except ValueError:
            return False

    async def check_demotion_triggers(self, strategy_id: int):
        """
        定时巡检调用（见§10定时任务），检测是否触发自动降级
        与晋级不同：降级判定一旦触发立即执行，不需要人工确认（资金安全优先）
        """
        strategy = await self._get_strategy(strategy_id)
        current_stage = StrategyStage(strategy['lifecycle_stage'])

        if current_stage not in DEMOTION_TRIGGERS:
            return

        trigger_config = DEMOTION_TRIGGERS[current_stage]
        metrics = await self._get_recent_performance(strategy_id, current_stage)

        triggered_reasons = []
        if metrics.get('consecutive_loss_days', 0) >= trigger_config.get('consecutive_loss_days', 999):
            triggered_reasons.append(f"连续亏损{metrics['consecutive_loss_days']}天")
        if metrics.get('current_drawdown', 0) <= trigger_config.get('drawdown_breach_pct', -999):
            triggered_reasons.append(f"回撤达{metrics['current_drawdown']:.1f}%")
        if 'sharpe_below' in trigger_config and metrics.get('rolling_sharpe', 999) < trigger_config['sharpe_below']:
            triggered_reasons.append(f"滚动夏普跌至{metrics['rolling_sharpe']:.2f}")

        if triggered_reasons:
            await self.transition(
                strategy_id=strategy_id,
                target_stage=trigger_config['action'],
                operator='system_auto_demotion',
                reason='；'.join(triggered_reasons),
                force=True,   # 降级允许系统自动执行，不需要走晋级评估
            )

    async def _get_strategy(self, strategy_id): ...
    async def _get_recent_performance(self, strategy_id, stage): ...
```

## 4. 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                  策略生命周期完整流程                            │
│                                                                  │
│  DRAFT ──创建──> BACKTEST ──通过评估──> WALK_FORWARD            │
│                  (21+27文档)            (28_29文档)              │
│                                              │                   │
│                                       通过评估│                   │
│                                              ▼                   │
│                                       PAPER_TRADING              │
│                                       (≥90天)                    │
│                                              │                   │
│                                       通过评估│                   │
│                                              ▼                   │
│                                          TRIAL                   │
│                                       (≥30天，≤5%资金)            │
│                                              │                   │
│                                       通过评估│                   │
│                                              ▼                   │
│                                       PRODUCTION                 │
│                                       (完整资金额度)               │
│                                              │                   │
│                                  持续监控（DemotionMonitor）       │
│                                              │                   │
│                                      触发降级条件│                  │
│                                              ▼                   │
│                                       DEPRECATED ──> ARCHIVED    │
│                                                                  │
│  每一步晋级：PromotionEvaluator 自动核验量化条件                  │
│  每一步降级：DemotionMonitor 持续巡检，触发即执行（不需等待）       │
│  所有转换：StrategyLifecycleManager 统一入口，写入审计日志         │
└──────────────────────────────────────────────────────────────┘
```

## 5. 数据流

```
1. 策略通过 21_STRATEGY_FACTORY.md 的API创建，初始 lifecycle_stage = 'DRAFT'
2. 人工或自动触发回测（28_29文档 BacktestEngine），结果写入 backtest.results
3. 人工调用 POST /api/v1/strategy/{id}/promote，触发 PromotionEvaluator.evaluate()
4. 评估通过 → StrategyLifecycleManager.transition() → 状态变为 BACKTEST
   评估不通过 → 返回 failed_conditions，前端展示具体差距
5. 同样流程推进到 WALK_FORWARD（依赖28_29文档的WalkForwardRunner结果）
6. 进入 PAPER_TRADING 后，系统按纸盘模式自动运行该策略（OrderManager mode='paper'）
7. 90天后再次调用 promote 接口，PromotionEvaluator 聚合纸盘期间所有 trade.account_records
8. 通过则进入 TRIAL，此时 OrderManager 切换为 mode='live'，但资金分配上限为总资金5%
   （需要在 35_38文档的 OrderManager 基础上新增资金分配比例检查）
9. TRIAL期间，每日对账（35_38文档的ReconciliationService）结果写入reconciliation_logs
10. 30天后再次评估，通过则进入 PRODUCTION，资金分配上限解除
11. PRODUCTION期间，DemotionMonitor 每日巡检（见§10），触发降级条件立即执行降级
12. 所有状态变更记录到 strategy.lifecycle_audit_log，前端"策略管理"页面可查看完整时间线
```

## 6. 数据库设计（新增数据表）

```sql
-- 扩展现有 strategy.strategies 表（21_STRATEGY_FACTORY.md中定义，此处为ALTER）
ALTER TABLE strategy.strategies
    ADD COLUMN lifecycle_stage VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    ADD COLUMN stage_entered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN capital_allocation_ratio NUMERIC(5,4) DEFAULT 0;  -- TRIAL阶段的资金占比上限

-- 生命周期审计日志
CREATE TABLE strategy.lifecycle_audit_log (
    id              BIGSERIAL       PRIMARY KEY,
    strategy_id     INT             NOT NULL REFERENCES strategy.strategies(id),
    from_stage      VARCHAR(20)     NOT NULL,
    to_stage        VARCHAR(20)     NOT NULL,
    operator        VARCHAR(50)     NOT NULL,        -- 'system_auto_demotion' 或具体人名
    reason          TEXT            NOT NULL,
    is_promotion    BOOLEAN         NOT NULL,
    was_forced      BOOLEAN         DEFAULT FALSE,    -- 是否绕过了PromotionEvaluator（应极少发生）
    metrics_snapshot JSONB,                           -- 转换时刻的完整指标快照
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX idx_lifecycle_audit_strategy ON strategy.lifecycle_audit_log(strategy_id, created_at DESC);

-- 晋级评估历史（即使未通过也记录，用于追踪策略改进趋势）
CREATE TABLE strategy.promotion_evaluations (
    id              BIGSERIAL       PRIMARY KEY,
    strategy_id     INT             NOT NULL REFERENCES strategy.strategies(id),
    current_stage   VARCHAR(20)     NOT NULL,
    target_stage    VARCHAR(20)     NOT NULL,
    eligible        BOOLEAN         NOT NULL,
    actual_metrics  JSONB,
    failed_conditions JSONB,
    evaluated_at    TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX idx_promotion_eval_strategy ON strategy.promotion_evaluations(strategy_id, evaluated_at DESC);
```

## 7. API设计

```
GET  /api/v1/strategy/{id}/lifecycle
     当前生命周期状态、进入时间、距离下次评估的剩余天数

POST /api/v1/strategy/{id}/evaluate-promotion
     手动触发晋级评估（不执行转换，只返回评估结果，供人工查看差距）

POST /api/v1/strategy/{id}/promote
     执行晋级（内部会先调用evaluate-promotion的逻辑，不通过则拒绝）
     Body: {operator, reason}

POST /api/v1/strategy/{id}/demote
     人工手动降级（force=true场景，如发现策略逻辑bug需紧急下线）
     Body: {target_stage, operator, reason}

GET  /api/v1/strategy/{id}/lifecycle-history
     完整状态变更时间线（用于前端展示）

GET  /api/v1/strategy/lifecycle-summary
     所有策略的当前阶段分布概览（用于Dashboard展示"3个纸盘中，1个试运行中，2个生产中"）
```

## 8. AI Agent职责

**本模块不新增LLM Agent，且明确禁止LLM参与晋级判定。** 这是刻意的设计决策：晋级条件必须是确定性的、可审计的、不受Prompt措辞影响的判断，否则会引入"AI说可以就可以"的资金安全漏洞。

唯一允许的AI参与：在`POST /api/v1/strategy/{id}/evaluate-promotion`返回`failed_conditions`后，前端可以调用一个**纯展示性质**的LLM调用，把冷冰冰的指标差距"翻译"成易懂的文字建议（例如"当前夏普比率0.65，距离1.0的要求还差0.35，可能需要优化止损逻辑减少震荡市中的虚假信号"）。这个LLM调用**只生成建议文本，不能修改eligible字段的值**，必须在代码层面做隔离。

## 9. 前端页面设计

新增 **策略生命周期** 视图，挂载在现有"策略管理"页面（42_44文档已定义）内，新增一个Tab：

```
策略管理页面
├── Tab 1: 策略列表（现有内容）
└── Tab 2: 生命周期看板（新增，类似Kanban/Trello视图）

    DRAFT      BACKTEST    WALK_FORWARD   PAPER_TRADING    TRIAL      PRODUCTION
    ┌─────┐    ┌─────┐     ┌─────┐        ┌─────┐         ┌─────┐    ┌─────┐
    │策略A│    │策略B│     │策略C│        │策略D │         │策略E│    │策略F│
    │     │    │     │     │     │        │ 67/90│         │12/30│    │     │
    └─────┘    └─────┘     └─────┘        └─────┘         └─────┘    └─────┘

每张卡片显示：策略名称、当前阶段停留天数（进度条形式：67/90天）、距离晋级的差距摘要
点击卡片展开：完整指标对比表（实际值 vs 要求值，颜色区分达标/未达标）
"申请晋级"按钮：仅当 PromotionEvaluator 返回 eligible=true 时高亮可点击，否则置灰并显示差距提示
```

## 10. 定时任务

```python
# 新增到 worker/celery_app.py 的 beat_schedule

'strategy-demotion-check-daily': {
    'task': 'tasks.check_all_strategy_demotion',
    'schedule': crontab(hour=16, minute=0),   # 收盘后检查降级条件
},
'strategy-promotion-reminder': {
    'task': 'tasks.notify_promotion_eligible_strategies',
    'schedule': crontab(hour=9, minute=0),    # 每日开盘前提醒：哪些策略已满足晋级条件待人工审批
},
```

```python
# worker/tasks/strategy_lifecycle.py

@shared_task(name='tasks.check_all_strategy_demotion', queue='normal')
def check_all_strategy_demotion():
    """对所有 TRIAL 和 PRODUCTION 阶段的策略检查降级条件"""
    import asyncio
    from app.strategy.lifecycle_manager import StrategyLifecycleManager
    from app.strategy.lifecycle import StrategyStage

    async def _run():
        from app.db import get_db
        async with get_db() as db:
            strategies = await db.fetch("""
                SELECT id FROM strategy.strategies
                WHERE lifecycle_stage IN ('TRIAL', 'PRODUCTION')
            """)
            manager = StrategyLifecycleManager(db, ws_manager=None)
            for s in strategies:
                await manager.check_demotion_triggers(s['id'])

    asyncio.run(_run())


@shared_task(name='tasks.notify_promotion_eligible_strategies', queue='normal')
def notify_promotion_eligible_strategies():
    """每日检查哪些策略已满足晋级条件，但晋级动作必须人工确认（不自动晋级）"""
    import asyncio
    from app.strategy.promotion_evaluator import PromotionEvaluator

    async def _run():
        from app.db import get_db
        async with get_db() as db:
            strategies = await db.fetch("""
                SELECT id, name FROM strategy.strategies
                WHERE lifecycle_stage IN ('BACKTEST', 'WALK_FORWARD', 'PAPER_TRADING', 'TRIAL')
            """)
            evaluator = PromotionEvaluator(db)
            eligible_list = []
            for s in strategies:
                result = await evaluator.evaluate(s['id'])
                if result['eligible']:
                    eligible_list.append(s['name'])

            if eligible_list:
                # 推送钉钉通知（复用02文档已定义的DINGTALK_WEBHOOK配置）
                await _send_dingtalk_notification(
                    f"以下策略已满足晋级条件，待人工审批：{', '.join(eligible_list)}"
                )

    asyncio.run(_run())
```

## 11. 配置项

```env
# ── 策略生命周期 ──
LIFECYCLE_PAPER_TRADING_MIN_DAYS=90      # 纸盘最短运行天数（硬编码到代码逻辑，此处仅作展示用途）
LIFECYCLE_TRIAL_MIN_DAYS=30              # 小资金试运行最短天数
LIFECYCLE_TRIAL_MAX_CAPITAL_RATIO=0.05   # 试运行阶段最大资金占比
LIFECYCLE_AUTO_DEMOTION_ENABLED=true     # 是否启用自动降级（生产环境强烈建议true，不应关闭）
LIFECYCLE_PROMOTION_REQUIRE_DUAL_APPROVAL=false  # 是否要求双人审批才能晋级到PRODUCTION（建议实盘阶段开启）
```

## 12. 开发优先级

属于 **跨阶段基础设施**，建议在 `03_DEVELOPMENT_ROADMAP.md` 的 **Phase 4（回测完善）** 阶段开始搭建状态机骨架（此时已有回测和Walk-Forward的产出数据可供晋级评估使用），但**完整功能必须在Phase 5（实盘接入）开始前全部完成并测试**，因为这是实盘资金分配的前置闸门，晚于这个时间点会导致Phase 5的"纸盘验证"环节缺少正式的状态管理，退化为人工口头确认（不可审计，不符合真实资金系统的合规要求）。

这是文档中明确标记**P0必须**的两个新增模块之一（另一个是Market State Engine），原因相同：缺少这个机制，整个系统就没有"安全地引入新策略"的能力，每次迭代都要靠人工记忆和口头约定，在团队扩大或人员变动后极易出现"忘记了某策略其实还没验证完就上线了"的事故。

## 13. 验收标准（Definition of Done）

```
□ ALLOWED_TRANSITIONS 状态机拒绝所有非法跳转（单元测试覆盖：DRAFT直接跳PRODUCTION必须被拒绝）
□ PromotionEvaluator 对纸盘阶段策略的评估，能正确识别"交易天数不足"和"回撤超标"两类典型不通过场景
□ force=True 的降级转换不需要PromotionEvaluator介入，能立即执行（验证DemotionMonitor的及时性）
□ force=True 不能被用于晋级类转换（代码层面阻止，即使传入force=True，is_promotion=True时仍强制走评估）
□ 策略从TRIAL晋级到PRODUCTION后，capital_allocation_ratio字段正确从0.05变为1.0（或对应配置值）
□ lifecycle_audit_log 完整记录每次转换，包含metrics_snapshot（晋级时刻的指标快照，供事后审计）
□ DemotionMonitor 在策略触发"连续10日亏损"后，24小时内（下一次每日巡检）自动执行降级
□ 前端生命周期看板正确展示进度条（如"67/90天"）且数据与后端API一致
□ 钉钉通知（晋级提醒）在策略满足条件后的下一个工作日09:00前送达
```

## 14. 与现有系统如何集成

**集成点1：`21_STRATEGY_FACTORY.md`的`strategy.strategies`表需要ALTER新增字段**（见§6），这是唯一对现有表结构的修改，向后兼容（新字段有默认值，不影响现有逻辑）。

**集成点2：`28_29_WALKFORWARD_AUTOML.md`的`WalkForwardRunner._aggregate_oos_results()`的返回结果直接作为`PromotionEvaluator._gather_walkforward_metrics()`的数据源**，不需要重新计算，只需要在Walk-Forward任务完成后把结果同步写入便于查询的字段（或直接JOIN查询`backtest.results`表）。

**集成点3：`35_38_TRADE_EXECUTION.md`的`OrderManager.create_order()`需要新增一项检查：** 当策略处于`TRIAL`阶段时，订单金额不能导致该策略累计仓位超过`capital_allocation_ratio`限制：

```python
# 在 OrderManager.create_order() 中新增（紧跟在熔断检查之后，风控检查之前）
async def create_order(self, request: OrderRequest, mode: str) -> dict:
    # ... 原有幂等检查、熔断检查 ...

    # 新增：策略资金分配比例检查（仅TRIAL阶段策略生效）
    if request.strategy_id:
        strategy = await self._get_strategy(request.strategy_id)
        if strategy['lifecycle_stage'] == 'TRIAL':
            allocation_check = await self._check_capital_allocation(
                request.strategy_id, request, strategy['capital_allocation_ratio']
            )
            if not allocation_check['passed']:
                return {'success': False, 'message': allocation_check['message']}

    # ... 原有风控检查、执行逻辑 ...
```

**集成点4：`35_38文档`的`ReconciliationService`需要新增`reconciliation_logs`表的写入逻辑**（目前文档中对账结果只通过WebSocket推送和日志打印，没有持久化表）。本文档`PromotionEvaluator._gather_trial_metrics()`依赖这张表统计`reconciliation_clean_days`，因此需要回头给35_38文档的`ReconciliationService.reconcile_positions()`补充落库逻辑：

```sql
-- 需要补充到 06_INFRA_DATABASE.md 或本文档的schema中
CREATE TABLE trade.reconciliation_logs (
    id              BIGSERIAL       PRIMARY KEY,
    strategy_id     INT,
    mode            VARCHAR(15)     NOT NULL,
    issues_found    INT             DEFAULT 0,
    issues_detail   JSONB,
    reconciled_at   TIMESTAMPTZ     DEFAULT NOW()
);
```

**集成点5：前端"策略管理"页面**（42_44文档已定义CRUD界面）新增Tab，不创建新的顶级路由，保持菜单结构稳定。

**不需要修改的部分：** `21文档`的`StrategyFactory`和所有具体策略类（MA/MACD/RSI/Hybrid）完全不变，生命周期管理是策略实例的"外层包装"，不侵入策略计算逻辑本身。
