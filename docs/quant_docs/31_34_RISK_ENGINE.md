# 31-34 — 风控系统完整设计

> ⚠️ **风控是真实资金系统的最后防线。任何代码路径都不能绕过风控检查。**

---

## 1. 风控引擎架构

```
风控系统分为两个维度：

维度1：时机（何时检查）
  ├── 交易前检查（Pre-Trade Check）：同步，阻断违规订单
  └── 实时监控（Real-time Monitor）：异步，持续监控持仓

维度2：性质（如何响应）
  ├── 硬约束（Hard Constraint）：直接阻断，无例外
  └── 软约束（Soft Constraint）：发出告警，允许人工确认后继续
```

---

## 2. 风控规则完整定义

```python
# backend/app/risk/rules.py

from dataclasses import dataclass
from typing import Callable, Optional

@dataclass
class RiskRule:
    code: str
    name: str
    rule_type: str              # position / loss / frequency / concentration / liquidity
    is_hard: bool               # 硬约束 vs 软约束
    threshold: float
    action: str                 # block / alert / reduce / fuse
    description: str

# 完整风控规则集
RISK_RULES = [
    # ── 仓位类 ──
    RiskRule('MAX_SINGLE_POSITION', '单票最大仓位',
             'position', is_hard=True, threshold=0.10, action='block',
             description='单只股票市值不得超过总资产的10%'),

    RiskRule('MAX_TOTAL_POSITION', '总仓位上限',
             'position', is_hard=True, threshold=0.80, action='block',
             description='总持仓市值不得超过总资产的80%，保留20%现金缓冲'),

    RiskRule('WARN_SINGLE_POSITION', '单票仓位预警',
             'position', is_hard=False, threshold=0.08, action='alert',
             description='单票超过8%发出预警'),

    RiskRule('WARN_TOTAL_POSITION', '总仓位预警',
             'position', is_hard=False, threshold=0.70, action='alert',
             description='总仓位超过70%发出预警'),

    RiskRule('MAX_SECTOR_CONCENTRATION', '行业集中度上限',
             'concentration', is_hard=True, threshold=0.40, action='block',
             description='单一行业持仓不得超过总资产40%（防行业系统性风险）'),

    # ── 亏损类 ──
    RiskRule('MAX_DAILY_LOSS', '日最大亏损熔断',
             'loss', is_hard=True, threshold=0.03, action='fuse',
             description='单日亏损超过3%立即停止所有交易，等待人工审核'),

    RiskRule('MAX_DRAWDOWN', '最大回撤熔断',
             'loss', is_hard=True, threshold=0.15, action='fuse',
             description='从历史最高净值回撤超过15%触发全面熔断'),

    RiskRule('MAX_SINGLE_TRADE_LOSS', '单笔交易最大亏损',
             'loss', is_hard=True, threshold=0.05, action='block',
             description='若止损价设置意味着单笔损失超过5%，拒绝该订单'),

    RiskRule('WARN_WEEKLY_LOSS', '周亏损预警',
             'loss', is_hard=False, threshold=0.05, action='alert',
             description='单周累计亏损超过5%发出预警'),

    # ── 频率类 ──
    RiskRule('MAX_DAILY_ORDER_COUNT', '日下单次数上限',
             'frequency', is_hard=True, threshold=20, action='block',
             description='单日下单次数超过20次阻断，防止过度交易'),

    RiskRule('MIN_HOLDING_DAYS', '最小持仓天数',
             'frequency', is_hard=False, threshold=1, action='alert',
             description='持仓不足1天即卖出触发预警（T+1限制下此规则自动满足）'),

    # ── 流动性类 ──
    RiskRule('MIN_DAILY_AMOUNT', '最低日成交额',
             'liquidity', is_hard=True, threshold=5000_0000, action='block',
             description='日成交额低于5000万的股票不允许买入（流动性不足）'),

    RiskRule('MAX_ORDER_VOLUME_RATIO', '单笔订单量比',
             'liquidity', is_hard=True, threshold=0.10, action='block',
             description='单笔买入量不得超过该股日成交量的10%（防冲击成本过高）'),

    # ── ST/特殊股票 ──
    RiskRule('BLOCK_ST', '禁止买入ST股',
             'special', is_hard=True, threshold=0, action='block',
             description='禁止买入任何ST/*ST股票'),

    RiskRule('BLOCK_NEW_STOCK', '禁止买入次新股',
             'special', is_hard=True, threshold=60, action='block',
             description='上市不足60日的次新股禁止买入（涨跌停限制不同）'),
]
```

---

## 3. 交易前风控检查器

```python
# backend/app/risk/checker.py

from dataclasses import dataclass
from typing import List
from datetime import datetime, date

@dataclass
class CheckResult:
    rule_code: str
    passed: bool
    severity: str           # BLOCK / WARN
    message: str
    actual_value: float
    threshold: float

@dataclass
class RiskCheckReport:
    passed: bool            # 整体通过（无BLOCK）
    blocked_by: List[str]   # 触发BLOCK的规则列表
    warnings: List[str]     # 触发WARN的规则列表
    checks: List[CheckResult]


class PreTradeRiskChecker:
    """
    交易前同步风控检查
    所有check必须通过才能下单
    """

    def __init__(self, db_session, risk_monitor):
        self.db = db_session
        self.monitor = risk_monitor

    def check(self, order_request: dict, mode: str) -> RiskCheckReport:
        """
        执行全量风控检查
        order_request: {stock_code, side, quantity, limit_price, signal_id}
        """
        checks = []

        # 1. 基础信息检查
        stock = self._get_stock(order_request['stock_code'])
        if stock is None:
            return RiskCheckReport(
                passed=False,
                blocked_by=['STOCK_NOT_FOUND'],
                warnings=[],
                checks=[CheckResult('STOCK_NOT_FOUND', False, 'BLOCK',
                                   '股票代码不存在', 0, 0)]
            )

        portfolio = self.monitor.get_portfolio_snapshot(mode)
        price = order_request.get('limit_price') or self._get_current_price(order_request['stock_code'])
        order_value = price * order_request['quantity']

        # 2. 禁止买入ST
        if order_request['side'] == 'BUY':
            checks.append(self._check_st(stock))

        # 3. 禁止买入次新股
        if order_request['side'] == 'BUY':
            checks.append(self._check_new_stock(stock))

        # 4. 单票仓位检查（只对BUY生效）
        if order_request['side'] == 'BUY':
            checks.append(self._check_single_position(
                order_request['stock_code'], order_value, portfolio
            ))

        # 5. 总仓位检查（只对BUY生效）
        if order_request['side'] == 'BUY':
            checks.append(self._check_total_position(order_value, portfolio))

        # 6. 日亏损检查（任何操作前检查）
        checks.append(self._check_daily_loss(portfolio))

        # 7. 最大回撤检查
        checks.append(self._check_drawdown(portfolio))

        # 8. 下单频率检查
        checks.append(self._check_order_frequency(mode))

        # 9. 流动性检查（只对BUY生效）
        if order_request['side'] == 'BUY':
            checks.extend(self._check_liquidity(
                order_request['stock_code'], order_request['quantity']
            ))

        # 10. 行业集中度（只对BUY生效）
        if order_request['side'] == 'BUY':
            checks.append(self._check_sector_concentration(stock, order_value, portfolio))

        # 汇总结果
        blocked = [c.rule_code for c in checks if not c.passed and c.severity == 'BLOCK']
        warnings = [c.rule_code for c in checks if not c.passed and c.severity == 'WARN']

        # 记录风控事件
        for check in checks:
            if not check.passed:
                self._log_risk_event(check, order_request, mode)

        return RiskCheckReport(
            passed=len(blocked) == 0,
            blocked_by=blocked,
            warnings=warnings,
            checks=checks
        )

    def _check_st(self, stock) -> CheckResult:
        is_st = stock.get('is_st', False)
        return CheckResult(
            rule_code='BLOCK_ST', passed=not is_st,
            severity='BLOCK' if is_st else 'BLOCK',
            message=f"{'ST股票，禁止买入' if is_st else 'ST检查通过'}",
            actual_value=1 if is_st else 0, threshold=0
        )

    def _check_new_stock(self, stock) -> CheckResult:
        from datetime import date
        list_date = stock.get('list_date')
        if list_date is None:
            return CheckResult('BLOCK_NEW_STOCK', True, 'BLOCK', '上市日期未知，允许', 0, 60)
        days_listed = (date.today() - list_date).days
        passed = days_listed >= 60
        return CheckResult(
            rule_code='BLOCK_NEW_STOCK', passed=passed,
            severity='BLOCK',
            message=f"上市{days_listed}日，{'不足60日禁止买入' if not passed else '通过'}",
            actual_value=days_listed, threshold=60
        )

    def _check_single_position(self, stock_code, order_value, portfolio) -> CheckResult:
        threshold = 0.10
        total_assets = portfolio['total_assets']

        current_position_value = portfolio['positions'].get(stock_code, {}).get('market_value', 0)
        new_position_value = current_position_value + order_value
        new_ratio = new_position_value / total_assets if total_assets > 0 else 0

        passed = new_ratio <= threshold
        warn_threshold = 0.08
        severity = 'BLOCK' if not passed else ('WARN' if new_ratio > warn_threshold else 'BLOCK')

        return CheckResult(
            rule_code='MAX_SINGLE_POSITION' if not passed else 'WARN_SINGLE_POSITION',
            passed=passed,
            severity=severity,
            message=f"买入后{stock_code}仓位将达{new_ratio:.1%}，{'超过10%上限' if not passed else '超过8%预警线' if new_ratio > warn_threshold else '正常'}",
            actual_value=new_ratio, threshold=threshold
        )

    def _check_total_position(self, order_value, portfolio) -> CheckResult:
        threshold = 0.80
        total_assets = portfolio['total_assets']
        current_mkt_value = portfolio['total_market_value']
        new_ratio = (current_mkt_value + order_value) / total_assets if total_assets > 0 else 0

        passed = new_ratio <= threshold
        return CheckResult(
            rule_code='MAX_TOTAL_POSITION', passed=passed,
            severity='BLOCK',
            message=f"买入后总仓位将达{new_ratio:.1%}，{'超过80%上限' if not passed else '通过'}",
            actual_value=new_ratio, threshold=threshold
        )

    def _check_daily_loss(self, portfolio) -> CheckResult:
        threshold = 0.03
        daily_pnl_pct = portfolio.get('daily_pnl_pct', 0)
        # 亏损为负数
        actual_loss = abs(min(daily_pnl_pct, 0))
        passed = actual_loss <= threshold
        return CheckResult(
            rule_code='MAX_DAILY_LOSS', passed=passed,
            severity='BLOCK',
            message=f"今日已亏损{actual_loss:.2%}，{'超过3%日亏损限制' if not passed else '正常'}",
            actual_value=actual_loss, threshold=threshold
        )

    def _check_drawdown(self, portfolio) -> CheckResult:
        threshold = 0.15
        drawdown = abs(min(portfolio.get('drawdown_from_peak', 0), 0))
        passed = drawdown <= threshold
        return CheckResult(
            rule_code='MAX_DRAWDOWN', passed=passed,
            severity='BLOCK',
            message=f"当前回撤{drawdown:.2%}，{'超过15%熔断阈值' if not passed else '正常'}",
            actual_value=drawdown, threshold=threshold
        )

    def _check_order_frequency(self, mode) -> CheckResult:
        threshold = 20
        today_count = self._get_today_order_count(mode)
        passed = today_count < threshold
        return CheckResult(
            rule_code='MAX_DAILY_ORDER_COUNT', passed=passed,
            severity='BLOCK',
            message=f"今日已下单{today_count}次，{'达到20次上限' if not passed else '正常'}",
            actual_value=today_count, threshold=threshold
        )

    def _check_liquidity(self, stock_code, quantity) -> List[CheckResult]:
        quote = self._get_today_quote(stock_code)
        results = []

        # 最低日成交额
        min_amount = 5000_0000
        daily_amount = quote.get('amount', 0) if quote else 0
        results.append(CheckResult(
            rule_code='MIN_DAILY_AMOUNT', passed=daily_amount >= min_amount,
            severity='BLOCK',
            message=f"今日成交额{daily_amount/1e4:.0f}万，{'低于5000万流动性要求' if daily_amount < min_amount else '通过'}",
            actual_value=daily_amount, threshold=min_amount
        ))

        # 订单量不超过日成交量10%
        daily_volume = quote.get('volume', 0) if quote else 0
        if daily_volume > 0:
            volume_ratio = quantity / daily_volume
            results.append(CheckResult(
                rule_code='MAX_ORDER_VOLUME_RATIO', passed=volume_ratio <= 0.10,
                severity='BLOCK',
                message=f"订单量占日成交量{volume_ratio:.1%}，{'超过10%阈值' if volume_ratio > 0.10 else '通过'}",
                actual_value=volume_ratio, threshold=0.10
            ))

        return results

    def _check_sector_concentration(self, stock, order_value, portfolio) -> CheckResult:
        threshold = 0.40
        sector = stock.get('sector', '')
        if not sector:
            return CheckResult('MAX_SECTOR_CONCENTRATION', True, 'BLOCK', '行业未知，跳过集中度检查', 0, threshold)

        sector_value = sum(
            pos.get('market_value', 0)
            for code, pos in portfolio['positions'].items()
            if pos.get('sector') == sector
        )
        total_assets = portfolio['total_assets']
        new_ratio = (sector_value + order_value) / total_assets if total_assets > 0 else 0
        passed = new_ratio <= threshold

        return CheckResult(
            rule_code='MAX_SECTOR_CONCENTRATION', passed=passed,
            severity='BLOCK',
            message=f"买入后{sector}行业仓位将达{new_ratio:.1%}，{'超过40%限制' if not passed else '通过'}",
            actual_value=new_ratio, threshold=threshold
        )

    def _log_risk_event(self, check, order, mode):
        from app.db import get_db_session
        with get_db_session() as db:
            db.execute("""
                INSERT INTO risk.risk_events
                (rule_code, trigger_value, threshold, action_taken, detail)
                VALUES (%s, %s, %s, %s, %s)
            """, [
                check.rule_code, check.actual_value, check.threshold,
                'blocked' if not check.passed else 'warned',
                str({'order': order, 'message': check.message})
            ])

    def _get_stock(self, code): ...
    def _get_current_price(self, code): ...
    def _get_today_order_count(self, mode): ...
    def _get_today_quote(self, code): ...
```

---

## 4. 实时风控监控器

```python
# backend/app/risk/monitor.py

import asyncio
from datetime import datetime

class RealTimeRiskMonitor:
    """
    实时风控监控（异步后台运行）
    每30秒检查一次整体组合风险
    """

    def __init__(self, db, ws_manager, fuse_manager):
        self.db = db
        self.ws = ws_manager
        self.fuse = fuse_manager
        self._running = False

    async def start(self):
        """启动监控循环"""
        self._running = True
        while self._running:
            try:
                await self._check_portfolio_risk()
            except Exception as e:
                # 监控失败不能影响交易，只记录日志
                print(f"[RiskMonitor ERROR] {e}")
            await asyncio.sleep(30)

    async def _check_portfolio_risk(self):
        for mode in ['simulation', 'paper', 'live']:
            portfolio = self.get_portfolio_snapshot(mode)
            if portfolio['total_assets'] == 0:
                continue

            # 1. 检查日亏损
            daily_pnl_pct = portfolio.get('daily_pnl_pct', 0)
            if daily_pnl_pct < -0.03:
                await self._trigger_fuse(
                    mode=mode,
                    reason=f"日亏损{daily_pnl_pct:.2%}超过3%阈值",
                    portfolio=portfolio
                )
                return

            # 2. 检查最大回撤
            drawdown = portfolio.get('drawdown_from_peak', 0)
            if drawdown < -0.15:
                await self._trigger_fuse(
                    mode=mode,
                    reason=f"回撤{drawdown:.2%}超过15%熔断阈值",
                    portfolio=portfolio
                )
                return

            # 3. 预警：回撤接近阈值
            if drawdown < -0.12:
                await self.ws.broadcast('alerts', {
                    'type': 'risk_alert',
                    'level': 'WARNING',
                    'message': f'组合回撤已达{drawdown:.2%}，接近15%熔断线，请注意控制风险',
                    'timestamp': datetime.utcnow().isoformat()
                })

    async def _trigger_fuse(self, mode: str, reason: str, portfolio: dict):
        """触发熔断"""
        # 1. 标记熔断状态
        await self.fuse.activate(mode, reason, portfolio)

        # 2. 取消所有待执行订单
        await self._cancel_all_pending_orders(mode)

        # 3. 推送WebSocket告警
        await self.ws.broadcast('alerts', {
            'type': 'fuse_activated',
            'level': 'CRITICAL',
            'mode': mode,
            'reason': reason,
            'message': f'【熔断】{reason}，已停止{mode}模式所有交易',
            'timestamp': datetime.utcnow().isoformat()
        })

        # 4. 发送钉钉/邮件通知
        await self._send_emergency_notification(reason, portfolio)

        print(f"[FUSE ACTIVATED] mode={mode}, reason={reason}")

    async def _cancel_all_pending_orders(self, mode: str):
        """取消所有PENDING状态订单"""
        pending_orders = self.db.query("""
            SELECT id FROM trade.orders
            WHERE mode = %s AND status = 'PENDING'
        """, [mode]).fetchall()

        for order in pending_orders:
            self.db.execute("""
                UPDATE trade.orders SET status = 'CANCELLED', cancelled_at = NOW()
                WHERE id = %s
            """, [order['id']])

        self.db.commit()

    def get_portfolio_snapshot(self, mode: str) -> dict:
        """获取当前组合快照"""
        account = self.db.query("""
            SELECT * FROM trade.account_records
            WHERE mode = %s ORDER BY record_time DESC LIMIT 1
        """, [mode]).fetchone()

        positions = self.db.query("""
            SELECT p.*, s.sector FROM trade.positions p
            LEFT JOIN fundamental.stocks s ON p.stock_code = s.code
            WHERE p.mode = %s
        """, [mode]).fetchall()

        peak_value = self.db.query("""
            SELECT MAX(total_assets) as peak
            FROM trade.account_records WHERE mode = %s
        """, [mode]).fetchone()

        total_assets = account['total_assets'] if account else 0
        peak = peak_value['peak'] if peak_value else total_assets
        drawdown = (total_assets - peak) / peak if peak > 0 else 0

        return {
            'total_assets': total_assets,
            'cash': account['cash'] if account else 0,
            'total_market_value': account['market_value'] if account else 0,
            'daily_pnl': account['daily_pnl'] if account else 0,
            'daily_pnl_pct': account['daily_pnl'] / total_assets if total_assets > 0 else 0,
            'drawdown_from_peak': drawdown,
            'positions': {p['stock_code']: dict(p) for p in positions},
        }
```

---

## 5. 熔断管理器

```python
# backend/app/risk/fuse.py

class FuseManager:
    """熔断状态管理"""

    def __init__(self, db, redis_client):
        self.db = db
        self.redis = redis_client

    async def activate(self, mode: str, reason: str, portfolio: dict):
        """激活熔断"""
        import json
        # Redis中记录熔断状态（快速读取）
        fuse_key = f"fuse:{mode}"
        self.redis.set(fuse_key, json.dumps({
            'active': True,
            'reason': reason,
            'activated_at': datetime.utcnow().isoformat(),
        }))

        # 数据库持久化
        self.db.execute("""
            INSERT INTO risk.fuse_records
            (mode, fuse_reason, portfolio_snapshot)
            VALUES (%s, %s, %s)
        """, [mode, reason, json.dumps(portfolio)])
        self.db.commit()

    def is_fused(self, mode: str) -> bool:
        """检查是否处于熔断状态（每次下单前调用）"""
        fuse_key = f"fuse:{mode}"
        data = self.redis.get(fuse_key)
        if not data:
            return False
        import json
        return json.loads(data).get('active', False)

    async def recover(self, mode: str, approved_by: str, note: str):
        """
        熔断恢复（必须人工操作）
        只能通过管理界面触发，不能通过API自动恢复
        """
        # 关闭Redis熔断标记
        fuse_key = f"fuse:{mode}"
        self.redis.delete(fuse_key)

        # 更新数据库记录
        self.db.execute("""
            UPDATE risk.fuse_records
            SET is_active = FALSE,
                recovery_approved_by = %s,
                recovery_note = %s,
                recovered_at = NOW()
            WHERE mode = %s AND is_active = TRUE
        """, [approved_by, note, mode])
        self.db.commit()

        print(f"[FUSE RECOVERED] mode={mode}, by={approved_by}")
```

---

## 6. VaR实时计算

```python
# backend/app/risk/var_calculator.py

import numpy as np
import pandas as pd

class VaRCalculator:
    """
    实时VaR（风险价值）计算
    用于评估当前持仓的潜在损失
    """

    def calculate_portfolio_var(
        self,
        positions: dict,         # {stock_code: {quantity, market_value}}
        confidence: float = 0.95,
        horizon_days: int = 1,
        lookback_days: int = 252  # 回望期
    ) -> dict:
        """
        历史模拟法计算组合VaR
        confidence=0.95 意味着 "95%概率，1日亏损不超过VaR值"
        """
        stock_codes = list(positions.keys())
        if not stock_codes:
            return {'var': 0, 'cvar': 0, 'method': 'historical_simulation'}

        # 获取历史收益率
        historical_returns = self._get_historical_returns(stock_codes, lookback_days)

        # 计算持仓权重
        total_value = sum(p['market_value'] for p in positions.values())
        weights = {
            code: positions[code]['market_value'] / total_value
            for code in stock_codes
        }

        # 构建权重向量
        w = np.array([weights.get(code, 0) for code in historical_returns.columns])

        # 历史模拟：计算组合历史日收益率
        portfolio_returns = historical_returns.values @ w

        # VaR
        var_pct = np.percentile(portfolio_returns, (1 - confidence) * 100)
        var_amount = abs(var_pct) * total_value

        # CVaR（超出VaR的平均损失）
        cvar_pct = portfolio_returns[portfolio_returns <= var_pct].mean()
        cvar_amount = abs(cvar_pct) * total_value

        # 多日VaR（假设收益独立，用sqrt(T)缩放）
        var_horizon = var_amount * np.sqrt(horizon_days)

        return {
            'var_1d': round(var_amount, 2),
            'var_horizon': round(var_horizon, 2),
            'var_pct': round(abs(var_pct) * 100, 4),
            'cvar_1d': round(cvar_amount, 2),
            'cvar_pct': round(abs(cvar_pct) * 100, 4),
            'confidence': confidence,
            'horizon_days': horizon_days,
            'total_value': total_value,
            'method': 'historical_simulation',
            'interpretation': (
                f"以{confidence:.0%}置信度，未来{horizon_days}日最大损失不超过"
                f"¥{var_horizon:,.0f}（组合价值的{abs(var_pct)*np.sqrt(horizon_days)*100:.2f}%）"
            )
        }

    def _get_historical_returns(self, stock_codes: list, lookback: int) -> pd.DataFrame:
        """从数据库获取历史收益率"""
        # 实现略，从 market.klines 获取日线数据并计算收益率
        pass
```
