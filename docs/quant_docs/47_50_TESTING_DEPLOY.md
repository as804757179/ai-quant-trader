# 47-50 — 测试、监控与部署

---

# Part 1: 测试策略（47-48）

## 1. 测试层次

```
测试金字塔：

         ┌───────────────┐
         │   E2E Tests   │  少量（关键流程：下单→持仓更新）
         └───────┬───────┘
        ┌────────┴────────┐
        │ Integration Tests│  中量（API + DB + Redis联测）
        └────────┬─────────┘
    ┌────────────┴────────────┐
    │      Unit Tests         │  大量（业务逻辑、风控规则、因子计算）
    └─────────────────────────┘
    
特殊测试：
- 回测验证测试（防未来函数验证）
- 风控规则测试（必须100%覆盖）
- 对账测试（模拟数据不一致场景）
```

---

## 2. 后端单元测试

```python
# backend/tests/test_risk_checker.py

import pytest
from unittest.mock import MagicMock, patch
from app.risk.checker import PreTradeRiskChecker
from app.trade.base_trader import OrderRequest

@pytest.fixture
def mock_portfolio():
    return {
        'total_assets': 1_000_000,
        'cash': 500_000,
        'total_market_value': 500_000,
        'daily_pnl': -15_000,
        'daily_pnl_pct': -0.015,
        'drawdown_from_peak': -0.05,
        'positions': {
            '000001': {
                'market_value': 80_000,
                'sector': '银行',
                'total_qty': 1000,
                'available_qty': 1000
            }
        }
    }

@pytest.fixture
def normal_order():
    return {
        'stock_code': '300308',
        'side': 'BUY',
        'quantity': 1000,
        'limit_price': 45.0,
        'signal_id': 'test-signal-001',
    }

class TestPreTradeRiskChecker:

    def setup_method(self):
        self.db = MagicMock()
        self.monitor = MagicMock()
        self.checker = PreTradeRiskChecker(self.db, self.monitor)

    def test_normal_order_passes(self, mock_portfolio, normal_order):
        """正常订单应该通过所有检查"""
        self.monitor.get_portfolio_snapshot.return_value = mock_portfolio
        self.checker._get_stock = MagicMock(return_value={
            'is_st': False, 'list_date': None, 'sector': '电子'
        })
        self.checker._get_current_price = MagicMock(return_value=45.0)
        self.checker._get_today_order_count = MagicMock(return_value=3)
        self.checker._get_today_quote = MagicMock(return_value={
            'amount': 200_000_000, 'volume': 5_000_000
        })

        report = self.checker.check(normal_order, 'simulation')

        assert report.passed is True
        assert len(report.blocked_by) == 0

    def test_st_stock_blocked(self, mock_portfolio, normal_order):
        """ST股票应该被阻断"""
        self.monitor.get_portfolio_snapshot.return_value = mock_portfolio
        self.checker._get_stock = MagicMock(return_value={
            'is_st': True, 'list_date': None, 'sector': '其他'
        })

        report = self.checker.check(normal_order, 'simulation')

        assert report.passed is False
        assert 'BLOCK_ST' in report.blocked_by

    def test_daily_loss_limit_triggered(self, normal_order):
        """日亏损超3%应触发阻断"""
        portfolio = {
            'total_assets': 1_000_000,
            'cash': 500_000,
            'total_market_value': 500_000,
            'daily_pnl': -35_000,
            'daily_pnl_pct': -0.035,  # 亏损3.5%，超过3%限制
            'drawdown_from_peak': -0.035,
            'positions': {}
        }
        self.monitor.get_portfolio_snapshot.return_value = portfolio
        self.checker._get_stock = MagicMock(return_value={
            'is_st': False, 'list_date': None, 'sector': '电子'
        })

        report = self.checker.check(normal_order, 'simulation')

        assert report.passed is False
        assert 'MAX_DAILY_LOSS' in report.blocked_by

    def test_single_position_limit(self, mock_portfolio, normal_order):
        """单票仓位超10%应被阻断"""
        # 订单价值 = 45 * 2000 = 90,000，当前已有80,000，合计170,000 = 17%
        large_order = {**normal_order, 'quantity': 2000, 'limit_price': 45.0}
        self.monitor.get_portfolio_snapshot.return_value = mock_portfolio
        self.checker._get_stock = MagicMock(return_value={
            'is_st': False, 'list_date': None, 'sector': '电子'
        })
        self.checker._get_current_price = MagicMock(return_value=45.0)
        self.checker._get_today_order_count = MagicMock(return_value=3)
        self.checker._get_today_quote = MagicMock(return_value={
            'amount': 200_000_000, 'volume': 5_000_000
        })

        report = self.checker.check(large_order, 'simulation')

        assert report.passed is False
        assert 'MAX_SINGLE_POSITION' in report.blocked_by

    def test_drawdown_fuse(self, normal_order):
        """回撤超15%应触发熔断阻断"""
        portfolio_with_drawdown = {
            'total_assets': 850_000,
            'cash': 850_000,
            'total_market_value': 0,
            'daily_pnl': 0,
            'daily_pnl_pct': 0,
            'drawdown_from_peak': -0.16,  # 回撤16%
            'positions': {}
        }
        self.monitor.get_portfolio_snapshot.return_value = portfolio_with_drawdown
        self.checker._get_stock = MagicMock(return_value={
            'is_st': False, 'list_date': None, 'sector': '电子'
        })

        report = self.checker.check(normal_order, 'simulation')

        assert report.passed is False
        assert 'MAX_DRAWDOWN' in report.blocked_by


# backend/tests/test_lookahead_checker.py

from app.backtest.lookahead_checker import LookaheadChecker
import pandas as pd
from datetime import date

class TestLookaheadChecker:

    def setup_method(self):
        self.checker = LookaheadChecker()

    def test_financial_data_uses_publish_date(self):
        """财务数据必须使用publish_date而非report_date"""
        # 模拟：2024Q1报告，报告期3月31日，但4月28日才发布
        decisions = pd.DataFrame([{
            'id': 1,
            'date': date(2024, 4, 1),   # 4月1日做决策
            'stock_code': '000001',
            'action': 'BUY'
        }])

        data_used = pd.DataFrame([{
            'decision_id': 1,
            'data_type': 'financial_report',
            'data_date': date(2024, 3, 31),       # 报告期
            'available_date': date(2024, 4, 28),  # 实际发布日
        }])

        issues = self.checker.check_data_timeline(decisions, data_used)

        # 4月1日决策使用了4月28日才发布的数据 → 应该发现问题
        errors = [i for i in issues if i.severity == 'ERROR']
        assert len(errors) > 0

    def test_same_day_close_price_detection(self):
        """检测可能使用当日收盘价生成信号的代码"""
        strategy_code = """
def generate_signal(df, current_date):
    today_kline = get_kline(current_date)  # 获取今日K线
    if today_kline['close'] > ma20:        # 使用今日收盘价
        return 'BUY'
"""
        issues = self.checker.check_strategy(strategy_code)
        warnings = [i for i in issues if i.severity == 'WARNING']
        assert len(warnings) > 0


# backend/tests/test_metrics.py

from app.backtest.metrics import MetricsCalculator
import pandas as pd
import numpy as np

class TestMetricsCalculator:

    def setup_method(self):
        self.calc = MetricsCalculator()

    def test_sharpe_ratio_positive_returns(self):
        """正收益策略的夏普比率应为正"""
        dates = pd.date_range('2023-01-01', periods=252)
        equity = pd.Series(
            [1000 * (1.001 ** i) for i in range(252)],  # 日涨0.1%
            index=dates
        )
        returns = equity.pct_change().dropna()
        sharpe = self.calc.sharpe_ratio(returns)
        assert sharpe > 0

    def test_max_drawdown_calculation(self):
        """最大回撤计算测试"""
        equity = pd.Series([100, 110, 105, 120, 90, 95, 115], dtype=float)
        mdd = self.calc.max_drawdown(equity)
        # 从120跌到90 = 25%回撤
        assert abs(mdd - (-25.0)) < 0.1

    def test_win_rate(self):
        """胜率计算"""
        import pandas as pd
        trades = pd.DataFrame({'pnl': [100, -50, 200, -30, 150, -80]})
        win_rate = self.calc.win_rate(trades)
        assert win_rate == pytest.approx(50.0)  # 3胜3负 = 50%
```

---

## 3. API集成测试

```python
# backend/tests/test_api_trade.py

import pytest
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
class TestTradeAPI:

    async def test_create_order_simulation(self):
        """测试模拟盘下单"""
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/api/v1/trade/order", json={
                "stock_code": "000001",
                "side": "BUY",
                "order_type": "LIMIT",
                "quantity": 100,
                "limit_price": 10.0,
                "mode": "simulation"
            })
            assert response.status_code == 200
            data = response.json()
            assert data['success'] is True
            assert 'order_id' in data['data']

    async def test_order_quantity_validation(self):
        """订单数量必须是100的整数倍"""
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/api/v1/trade/order", json={
                "stock_code": "000001",
                "side": "BUY",
                "order_type": "LIMIT",
                "quantity": 150,  # 不是100的整数倍
                "limit_price": 10.0,
                "mode": "simulation"
            })
            assert response.status_code == 400

    async def test_duplicate_order_idempotent(self):
        """重复下单应返回已有订单（幂等性）"""
        order_data = {
            "stock_code": "000001",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": 100,
            "limit_price": 10.0,
            "mode": "simulation",
            "signal_id": "idempotent-test-001"
        }
        async with AsyncClient(app=app, base_url="http://test") as client:
            res1 = await client.post("/api/v1/trade/order", json=order_data)
            res2 = await client.post("/api/v1/trade/order", json=order_data)

            assert res1.status_code == 200
            assert res2.status_code == 200
            # 两次请求应返回同一个order_id
            assert res1.json()['data']['order_id'] == res2.json()['data']['order_id']
            assert res2.json()['data']['idempotent'] is True
```

---

# Part 2: 监控系统（48）

## 4. Prometheus 指标

```python
# backend/app/core/metrics.py

from prometheus_client import Counter, Histogram, Gauge, Summary

# AI调用指标
ai_calls_total = Counter(
    'ai_agent_calls_total',
    'Total AI agent calls',
    ['agent_name', 'model', 'status']
)
ai_latency = Histogram(
    'ai_agent_latency_seconds',
    'AI agent response latency',
    ['agent_name'],
    buckets=[1, 5, 10, 20, 30, 60]
)
ai_tokens = Counter(
    'ai_tokens_total',
    'Total AI tokens consumed',
    ['agent_name', 'direction']  # direction: input/output
)

# 交易指标
orders_total = Counter(
    'trade_orders_total',
    'Total trade orders',
    ['side', 'mode', 'status']
)
risk_blocks_total = Counter(
    'risk_blocks_total',
    'Total orders blocked by risk rules',
    ['rule_code', 'mode']
)

# 系统指标
portfolio_value = Gauge(
    'portfolio_total_assets',
    'Current portfolio total assets',
    ['mode']
)
portfolio_drawdown = Gauge(
    'portfolio_drawdown_pct',
    'Current portfolio drawdown percentage',
    ['mode']
)
active_signals = Gauge(
    'ai_active_signals_total',
    'Number of active AI signals'
)

# WebSocket连接数
ws_connections = Gauge(
    'ws_active_connections',
    'Active WebSocket connections',
    ['channel']
)

# 数据同步指标
data_sync_lag = Gauge(
    'data_sync_lag_seconds',
    'Data synchronization lag in seconds',
    ['data_type']
)


# 使用示例（在AI服务中）
def track_ai_call(agent_name: str, model: str):
    """装饰器：自动记录AI调用指标"""
    import functools
    import time

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.time()
            status = 'success'
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = 'error'
                raise
            finally:
                duration = time.time() - start
                ai_calls_total.labels(agent_name=agent_name, model=model, status=status).inc()
                ai_latency.labels(agent_name=agent_name).observe(duration)
        return wrapper
    return decorator
```

---

## 5. Grafana Dashboard 配置

```yaml
# docker/grafana/dashboards/quant_trader.json（结构示意）

panels:
  - title: "AI Agent调用延迟（P95）"
    type: graph
    targets:
      - expr: "histogram_quantile(0.95, rate(ai_agent_latency_seconds_bucket[5m]))"
    alert:
      conditions:
        - threshold: 25s
      message: "AI Agent响应超过25秒，可能影响信号质量"

  - title: "每分钟风控拦截次数"
    type: stat
    targets:
      - expr: "rate(risk_blocks_total[1m]) * 60"
    thresholds:
      - color: green,  value: 0
      - color: yellow, value: 5
      - color: red,    value: 10

  - title: "组合回撤（实时）"
    type: gauge
    targets:
      - expr: "portfolio_drawdown_pct{mode='live'}"
    thresholds:
      - color: green,  value: -5
      - color: yellow, value: -10
      - color: red,    value: -15
    alert:
      conditions:
        - threshold: -12   # 超过12%发告警
      message: "⚠️ 组合回撤接近15%熔断线"

  - title: "WebSocket活跃连接"
    type: timeseries
    targets:
      - expr: "ws_active_connections"

  - title: "AI Token消耗（每小时）"
    type: bargauge
    targets:
      - expr: "increase(ai_tokens_total[1h])"
    legend: "{{agent_name}} {{direction}}"
```

---

# Part 3: 部署指南（49-50）

## 6. 本地开发环境搭建

```bash
# 1. 克隆项目
git clone https://github.com/your-org/AI-Quant-Trader-Pro
cd AI-Quant-Trader-Pro

# 2. 初始化子模块
git submodule update --init --recursive

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填写：
# - OPENAI_API_KEY
# - ANTHROPIC_API_KEY
# - DB_PASSWORD
# - REDIS_PASSWORD

# 4. 启动所有服务
docker compose up -d

# 5. 等待服务就绪（约60秒）
docker compose ps

# 6. 初始化数据库
docker compose exec api alembic upgrade head

# 7. 导入股票基础数据
docker compose exec worker python scripts/seed_stocks.py

# 8. 初始化模拟账户（100万初始资金）
docker compose exec api python scripts/init_simulation_account.py --cash 1000000

# 9. 回填历史K线（可选，耗时较长）
docker compose exec worker python scripts/backfill_kline.py --years 3 --universe hs300

# 10. 访问系统
# 前端：http://localhost
# API文档：http://localhost/api/docs
# Grafana：http://localhost:3001
# Flower（Celery监控）：http://localhost:5555
```

---

## 7. 初始化脚本

```python
# backend/scripts/init_simulation_account.py

"""初始化模拟账户"""
import argparse
import sys
sys.path.insert(0, '/app')

from app.db import get_db_session

def init_simulation_account(cash: float, mode: str = 'simulation'):
    with get_db_session() as db:
        # 检查是否已有账户记录
        existing = db.execute("""
            SELECT id FROM trade.account_records WHERE mode = %s LIMIT 1
        """, [mode]).fetchone()

        if existing:
            print(f"账户 {mode} 已存在，跳过初始化")
            return

        db.execute("""
            INSERT INTO trade.account_records
            (mode, total_assets, cash, market_value, frozen_cash,
             daily_pnl, total_pnl, position_ratio, data_type)
            VALUES (%s, %s, %s, 0, 0, 0, 0, 0, 'init')
        """, [mode, cash, cash])
        db.commit()
        print(f"✅ {mode} 账户初始化完成，初始资金：¥{cash:,.2f}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cash', type=float, default=1_000_000)
    parser.add_argument('--mode', default='simulation')
    args = parser.parse_args()
    init_simulation_account(args.cash, args.mode)
```

---

## 8. 生产部署检查清单

```
部署前必检项：

基础设施
□ PostgreSQL + TimescaleDB 已启动，健康检查通过
□ Redis 已启动，密码已设置
□ 所有数据库迁移已执行（alembic upgrade head）
□ 股票基础数据已导入（seed_stocks）

安全配置
□ .env 中所有密码已替换默认值
□ .env 文件已加入 .gitignore
□ API Key已配置且有效（测试：运行 scripts/test_api_keys.py）
□ Nginx已配置SSL（生产环境）
□ 数据库端口只绑定127.0.0.1

风控配置
□ 风控规则已从代码初始化到数据库
□ 交易模式确认为 simulation（首次部署）
□ 日最大亏损/最大回撤参数已审核

监控配置
□ Prometheus 已配置告警规则
□ Grafana Dashboard已导入
□ 钉钉/邮件通知 Webhook 已配置

实盘切换前额外检查（v2.0+）
□ 纸盘至少运行90天，结果符合预期
□ QMT客户端已安装并连接
□ QMT账户ID已配置
□ 实盘风控规则已收紧（降低单笔仓位上限）
□ 至少2人审核并签字确认
□ 有回退方案（如何紧急切回模拟盘）
```

---

## 9. 常见问题排查

```bash
# Q: AI分析很慢或超时
# A: 检查AI API Key是否有效，网络是否能访问
docker compose exec api python scripts/test_api_keys.py

# Q: 数据库连接失败
docker compose logs postgres | tail -50
docker compose exec postgres pg_isready -U admin

# Q: K线数据为空
# A: 触发手动数据同步
docker compose exec worker python scripts/sync_kline.py --code 000001 --period 1d

# Q: WebSocket连接失败
# A: 检查nginx配置（需要支持WebSocket升级）
cat docker/nginx/nginx.conf | grep -A5 "upgrade"

# Q: Celery任务积压
docker compose exec api celery -A worker.celery_app inspect active
docker compose exec api celery -A worker.celery_app purge  # 清空队列（谨慎）

# Q: 回测任务卡住
docker compose logs worker | grep ERROR | tail -20
docker compose exec api python scripts/reset_stuck_backtest_tasks.py

# Q: 实盘持仓与券商不一致
# A: 手动触发对账
curl -X POST "http://localhost/api/v1/trade/reconcile?mode=live"
```
