# 21 — 策略工厂系统（Strategy Factory）

---

## 1. 策略工厂设计模式

```python
# backend/app/strategy/factory.py

from typing import Type, Dict
from .base_strategy import BaseStrategy

class StrategyFactory:
    """
    策略工厂：统一注册、实例化和管理所有策略
    支持热加载：新增策略只需继承BaseStrategy并注册
    """
    _registry: Dict[str, Type[BaseStrategy]] = {}

    @classmethod
    def register(cls, strategy_type: str):
        """装饰器：注册策略到工厂"""
        def decorator(strategy_class: Type[BaseStrategy]):
            cls._registry[strategy_type] = strategy_class
            return strategy_class
        return decorator

    @classmethod
    def create(cls, strategy_type: str, config: dict) -> BaseStrategy:
        """根据类型和配置创建策略实例"""
        if strategy_type not in cls._registry:
            raise ValueError(f"Unknown strategy type: {strategy_type}. "
                           f"Available: {list(cls._registry.keys())}")
        return cls._registry[strategy_type](config)

    @classmethod
    def list_available(cls) -> list:
        return list(cls._registry.keys())


# backend/app/strategy/base_strategy.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import pandas as pd

@dataclass
class StrategySignal:
    stock_code: str
    action: str          # BUY / SELL / HOLD
    confidence: float    # 0.0~1.0
    price: float
    quantity: Optional[int] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reason: str = ""

class BaseStrategy(ABC):
    """所有策略的基类"""

    def __init__(self, config: dict):
        self.config = config
        self.name = config.get('name', self.__class__.__name__)
        self.validate_config()

    @abstractmethod
    def validate_config(self):
        """验证策略配置，无效配置抛出ValueError"""
        pass

    @abstractmethod
    def generate_signal(
        self,
        stock_code: str,
        kline_df: pd.DataFrame,    # 历史K线数据（严格不含当日收盘后数据）
        context: dict              # 其他数据（资金流、基本面等）
    ) -> StrategySignal:
        """
        生成交易信号
        重要：kline_df 中的最后一行必须是昨日K线（非当日）
        信号将在下一个交易日执行
        """
        pass

    def calculate_position_size(
        self,
        portfolio_value: float,
        price: float,
        risk_pct: float = 0.02  # 每次交易风险不超过组合2%
    ) -> int:
        """凯利公式计算建议仓位（股数，必须是100的整数倍）"""
        max_risk_amount = portfolio_value * risk_pct
        if not hasattr(self, '_stop_loss_pct'):
            return 0
        stop_loss_amount_per_share = price * self._stop_loss_pct
        if stop_loss_amount_per_share <= 0:
            return 0
        quantity = int(max_risk_amount / stop_loss_amount_per_share / 100) * 100
        return max(quantity, 100)  # 最少买100股
```

---

## 2. 技术策略实现

### 2.1 MA均线策略

```python
# backend/app/strategy/technical/ma_strategy.py

import pandas as pd
from ..factory import StrategyFactory
from ..base_strategy import BaseStrategy, StrategySignal

@StrategyFactory.register('ma_crossover')
class MACrossoverStrategy(BaseStrategy):
    """
    均线交叉策略
    金叉（短均线上穿长均线）买入，死叉卖出
    """

    def validate_config(self):
        required = ['fast_period', 'slow_period']
        for key in required:
            if key not in self.config:
                raise ValueError(f"MA策略缺少必要参数: {key}")
        if self.config['fast_period'] >= self.config['slow_period']:
            raise ValueError("fast_period 必须小于 slow_period")

    def generate_signal(self, stock_code: str, kline_df: pd.DataFrame, context: dict) -> StrategySignal:
        fast = self.config['fast_period']
        slow = self.config['slow_period']

        if len(kline_df) < slow + 2:
            return StrategySignal(stock_code=stock_code, action='HOLD',
                                  confidence=0, price=kline_df['close'].iloc[-1])

        # 使用昨日收盘价计算（最后一行=昨日，倒数第二行=前日）
        # 这是防未来函数的关键：不用今日数据
        df = kline_df.copy()
        df['ma_fast'] = df['close'].rolling(fast).mean()
        df['ma_slow'] = df['close'].rolling(slow).mean()

        # 取最近两个完整计算点（均不包含今日）
        prev = df.iloc[-2]   # 前日
        curr = df.iloc[-1]   # 昨日（信号产生点）

        price = curr['close']
        action = 'HOLD'
        confidence = 0.5

        # 金叉：昨日发生
        if prev['ma_fast'] <= prev['ma_slow'] and curr['ma_fast'] > curr['ma_slow']:
            action = 'BUY'
            # 置信度：两均线距离越大，信号越强
            gap = (curr['ma_fast'] - curr['ma_slow']) / curr['ma_slow']
            confidence = min(0.5 + gap * 10, 0.85)
            self._stop_loss_pct = self.config.get('stop_loss_pct', 0.05)

        # 死叉
        elif prev['ma_fast'] >= prev['ma_slow'] and curr['ma_fast'] < curr['ma_slow']:
            action = 'SELL'
            confidence = 0.75

        return StrategySignal(
            stock_code=stock_code,
            action=action,
            confidence=confidence,
            price=price,
            stop_loss=price * (1 - self.config.get('stop_loss_pct', 0.05)) if action == 'BUY' else None,
            take_profit=price * (1 + self.config.get('take_profit_pct', 0.15)) if action == 'BUY' else None,
            reason=f"MA{fast}/MA{slow}{'金叉' if action=='BUY' else '死叉' if action=='SELL' else '无信号'}"
        )
```

### 2.2 MACD策略

```python
@StrategyFactory.register('macd')
class MACDStrategy(BaseStrategy):
    """MACD金叉死叉策略 + 柱状图背离确认"""

    def validate_config(self):
        self.config.setdefault('fast', 12)
        self.config.setdefault('slow', 26)
        self.config.setdefault('signal', 9)

    def generate_signal(self, stock_code: str, kline_df: pd.DataFrame, context: dict) -> StrategySignal:
        df = kline_df.copy()
        fast, slow, sig = self.config['fast'], self.config['slow'], self.config['signal']

        if len(df) < slow + sig + 5:
            return StrategySignal(stock_code=stock_code, action='HOLD', confidence=0, price=df['close'].iloc[-1])

        # 计算MACD
        ema_fast = df['close'].ewm(span=fast).mean()
        ema_slow = df['close'].ewm(span=slow).mean()
        df['macd'] = ema_fast - ema_slow
        df['signal_line'] = df['macd'].ewm(span=sig).mean()
        df['histogram'] = df['macd'] - df['signal_line']

        prev = df.iloc[-2]
        curr = df.iloc[-1]
        price = curr['close']

        action = 'HOLD'
        confidence = 0.0

        # 金叉
        if prev['macd'] <= prev['signal_line'] and curr['macd'] > curr['signal_line']:
            action = 'BUY'
            # MACD在零轴下方金叉更可靠
            if curr['macd'] < 0:
                confidence = 0.75
            else:
                confidence = 0.60

        # 死叉
        elif prev['macd'] >= prev['signal_line'] and curr['macd'] < curr['signal_line']:
            action = 'SELL'
            confidence = 0.70

        # 顶底背离（额外确认）
        # 价格创新高但MACD没创新高 → 顶部背离（卖出信号）
        if action == 'HOLD':
            recent = df.tail(20)
            if (curr['close'] == recent['close'].max() and
                curr['macd'] < recent['macd'].max() * 0.9):
                action = 'SELL'
                confidence = 0.65
                return StrategySignal(stock_code=stock_code, action=action,
                                      confidence=confidence, price=price,
                                      reason="MACD顶部背离，价格创新高但动量减弱")

        return StrategySignal(
            stock_code=stock_code, action=action, confidence=confidence, price=price,
            stop_loss=price * 0.95 if action == 'BUY' else None,
            reason=f"MACD({fast},{slow},{sig}) {'金叉' if action=='BUY' else '死叉' if action=='SELL' else '观望'}"
        )
```

### 2.3 RSI策略

```python
@StrategyFactory.register('rsi')
class RSIStrategy(BaseStrategy):
    """RSI超买超卖策略"""

    def validate_config(self):
        self.config.setdefault('period', 14)
        self.config.setdefault('oversold', 30)
        self.config.setdefault('overbought', 70)

    def generate_signal(self, stock_code: str, kline_df: pd.DataFrame, context: dict) -> StrategySignal:
        period = self.config['period']
        if len(kline_df) < period + 5:
            return StrategySignal(stock_code=stock_code, action='HOLD', confidence=0, price=kline_df['close'].iloc[-1])

        df = kline_df.copy()
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, 1e-10)
        df['rsi'] = 100 - 100 / (1 + rs)

        curr_rsi = df['rsi'].iloc[-1]
        prev_rsi = df['rsi'].iloc[-2]
        price = df['close'].iloc[-1]

        action = 'HOLD'
        confidence = 0.0

        # 超卖回升买入
        if prev_rsi <= self.config['oversold'] and curr_rsi > self.config['oversold']:
            action = 'BUY'
            confidence = 0.65 + (self.config['oversold'] - prev_rsi) / 100

        # 超买回落卖出
        elif prev_rsi >= self.config['overbought'] and curr_rsi < self.config['overbought']:
            action = 'SELL'
            confidence = 0.65

        return StrategySignal(
            stock_code=stock_code, action=action,
            confidence=min(confidence, 0.85), price=price,
            reason=f"RSI({period})={curr_rsi:.1f}，{'超卖回升' if action=='BUY' else '超买回落' if action=='SELL' else '正常区间'}"
        )
```

### 2.4 布林带策略

```python
@StrategyFactory.register('bollinger')
class BollingerBandsStrategy(BaseStrategy):
    """布林带突破/回归策略"""

    def validate_config(self):
        self.config.setdefault('period', 20)
        self.config.setdefault('std_dev', 2.0)
        self.config.setdefault('mode', 'reversion')  # reversion/breakout

    def generate_signal(self, stock_code: str, kline_df: pd.DataFrame, context: dict) -> StrategySignal:
        period = self.config['period']
        std = self.config['std_dev']

        df = kline_df.copy()
        df['mid'] = df['close'].rolling(period).mean()
        df['std'] = df['close'].rolling(period).std()
        df['upper'] = df['mid'] + std * df['std']
        df['lower'] = df['mid'] - std * df['std']

        prev = df.iloc[-2]
        curr = df.iloc[-1]
        price = curr['close']

        action = 'HOLD'
        confidence = 0.0

        if self.config['mode'] == 'reversion':
            # 均值回归：碰下轨买，碰上轨卖
            if prev['close'] <= prev['lower'] and curr['close'] > curr['lower']:
                action = 'BUY'
                confidence = 0.65
            elif prev['close'] >= prev['upper'] and curr['close'] < curr['upper']:
                action = 'SELL'
                confidence = 0.65
        else:  # breakout
            # 突破策略：突破上轨买，跌破下轨卖
            if prev['close'] <= prev['upper'] and curr['close'] > curr['upper']:
                action = 'BUY'
                confidence = 0.60
            elif prev['close'] >= prev['lower'] and curr['close'] < curr['lower']:
                action = 'SELL'
                confidence = 0.65

        return StrategySignal(
            stock_code=stock_code, action=action, confidence=confidence, price=price,
            reason=f"布林带({period},{std}) {self.config['mode']} {'触发' if action!='HOLD' else '观望'}"
        )
```

---

## 3. AI策略

```python
# backend/app/strategy/ai_strategy.py

@StrategyFactory.register('ai_driven')
class AIDrivenStrategy(BaseStrategy):
    """
    AI驱动策略：将AIService集成进策略框架
    信号完全由AI Agent决定
    """

    def validate_config(self):
        self.config.setdefault('min_confidence', 0.68)
        self.config.setdefault('agents', ['trend', 'fundamental', 'sentiment', 'shortterm'])

    async def generate_signal_async(self, stock_code: str, kline_df: pd.DataFrame, context: dict) -> StrategySignal:
        """AI策略必须用异步方法"""
        from app.ai.orchestrator import AgentOrchestrator
        orchestrator = AgentOrchestrator()
        ai_signal = await orchestrator.analyze(stock_code, context)

        action = ai_signal['action']
        confidence = ai_signal['confidence']

        if confidence < self.config['min_confidence']:
            action = 'HOLD'

        return StrategySignal(
            stock_code=stock_code,
            action=action,
            confidence=confidence,
            price=ai_signal['price_at'],
            reason=ai_signal['reason'],
        )

    def generate_signal(self, stock_code, kline_df, context):
        """同步接口（兼容回测引擎，内部运行事件循环）"""
        import asyncio
        return asyncio.run(self.generate_signal_async(stock_code, kline_df, context))


@StrategyFactory.register('hybrid')
class HybridStrategy(BaseStrategy):
    """
    混合策略：技术指标过滤 + AI确认
    流程：技术指标触发候选信号 → AI分析确认 → 输出最终信号
    """

    def validate_config(self):
        required = ['technical_type', 'technical_config', 'min_ai_confidence']
        for key in required:
            if key not in self.config:
                raise ValueError(f"混合策略缺少必要参数: {key}")

    def generate_signal(self, stock_code: str, kline_df: pd.DataFrame, context: dict) -> StrategySignal:
        # Step 1: 技术指标初筛
        tech_strategy = StrategyFactory.create(
            self.config['technical_type'],
            self.config['technical_config']
        )
        tech_signal = tech_strategy.generate_signal(stock_code, kline_df, context)

        # 只有技术信号为BUY时才触发AI分析（省成本）
        if tech_signal.action != 'BUY':
            return tech_signal

        # Step 2: AI确认
        import asyncio
        from app.ai.orchestrator import AgentOrchestrator
        orchestrator = AgentOrchestrator()
        ai_signal = asyncio.run(orchestrator.analyze(stock_code, context))

        if ai_signal['confidence'] < self.config['min_ai_confidence']:
            return StrategySignal(
                stock_code=stock_code, action='HOLD',
                confidence=ai_signal['confidence'], price=tech_signal.price,
                reason=f"技术面触发但AI置信度不足({ai_signal['confidence']:.0%})"
            )

        return StrategySignal(
            stock_code=stock_code,
            action='BUY',
            confidence=(tech_signal.confidence + ai_signal['confidence']) / 2,
            price=tech_signal.price,
            stop_loss=tech_signal.stop_loss,
            reason=f"技术+AI双确认：{tech_signal.reason} | {ai_signal['reason']}"
        )
```

---

## 4. 策略配置JSON格式

```json
{
  "strategy_configs": [
    {
      "name": "MA金叉策略",
      "type": "ma_crossover",
      "universe": "hs300",
      "config": {
        "fast_period": 5,
        "slow_period": 20,
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.15
      },
      "position": {
        "max_single_ratio": 0.08,
        "max_positions": 5
      }
    },
    {
      "name": "AI混合策略-科技板",
      "type": "hybrid",
      "universe": "custom:tech_stocks",
      "config": {
        "technical_type": "macd",
        "technical_config": {"fast": 12, "slow": 26, "signal": 9},
        "min_ai_confidence": 0.70
      },
      "position": {
        "max_single_ratio": 0.10,
        "max_positions": 3
      }
    }
  ]
}
```

---

## 5. 因子库（Factor Library）

```python
# backend/app/strategy/factors.py

import pandas as pd
import numpy as np

class FactorLibrary:
    """
    常用量化因子计算库
    所有因子计算必须保证：只使用截止date之前的数据
    """

    @staticmethod
    def momentum(close: pd.Series, period: int) -> float:
        """动量因子：N日收益率"""
        if len(close) < period + 1:
            return None
        return (close.iloc[-1] / close.iloc[-period-1] - 1) * 100

    @staticmethod
    def volatility(close: pd.Series, period: int = 20) -> float:
        """波动率因子：N日收益率标准差（年化）"""
        returns = close.pct_change().dropna()
        if len(returns) < period:
            return None
        return returns.tail(period).std() * np.sqrt(252) * 100

    @staticmethod
    def volume_price_trend(close: pd.Series, volume: pd.Series, period: int = 10) -> float:
        """量价趋势因子"""
        if len(close) < period:
            return None
        vpt = ((close.diff() / close.shift(1)) * volume).rolling(period).sum()
        return vpt.iloc[-1]

    @staticmethod
    def relative_strength(stock_close: pd.Series, index_close: pd.Series, period: int = 20) -> float:
        """相对强弱因子：个股vs大盘"""
        if len(stock_close) < period:
            return None
        stock_ret = stock_close.iloc[-1] / stock_close.iloc[-period] - 1
        index_ret = index_close.iloc[-1] / index_close.iloc[-period] - 1
        return stock_ret - index_ret

    @staticmethod
    def turnover_stability(turnover: pd.Series, period: int = 20) -> float:
        """换手率稳定性（低换手且稳定 = 机构持仓）"""
        if len(turnover) < period:
            return None
        mean_t = turnover.tail(period).mean()
        std_t = turnover.tail(period).std()
        return std_t / (mean_t + 1e-8)  # 变异系数，越小越稳定

    @staticmethod
    def money_flow_strength(fund_flow: pd.DataFrame, period: int = 5) -> float:
        """资金流强度因子"""
        if len(fund_flow) < period:
            return None
        recent = fund_flow.tail(period)
        main_net_total = recent['main_net_in'].sum()
        total_amount = recent['amount'].sum()
        if total_amount == 0:
            return 0
        return main_net_total / total_amount * 100  # 主力净流入占比（%）
```
