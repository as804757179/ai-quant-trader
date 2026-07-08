# 35-38 — 交易执行层完整设计

> ⚠️ **交易层是资金直接流动的地方，所有操作必须幂等、可追溯、事务安全。**

---

## 1. 交易层架构

```
OrderManager（订单生命周期管理）
        │
        ├── 下单前：PreTradeRiskChecker.check()  ← 硬约束
        ├── 幂等键检查（防重复下单）
        ├── FuseManager.is_fused()               ← 熔断检查
        │
        ▼
TraderRouter（根据mode路由到对应Trader）
        │
        ├── mode=simulation → SimulationTrader
        ├── mode=paper      → PaperTrader
        └── mode=live       → QMTTrader
        │
        ▼
执行结果回调
        │
        ├── 数据库事务：订单+持仓+账户（原子更新）
        ├── 审计日志记录
        └── WebSocket推送
```

---

## 2. 订单状态机

```
                    ┌─────────┐
                    │ CREATED │  （内存中，尚未持久化）
                    └────┬────┘
                         │ 风控通过 + 幂等键写入DB
                         ▼
                    ┌─────────┐
                    │ PENDING │  （已持久化，等待提交券商）
                    └────┬────┘
                         │ 提交到券商/模拟引擎
              ┌──────────┴──────────┐
              ▼                     ▼
        ┌──────────┐          ┌──────────┐
        │SUBMITTED │          │  FAILED  │  （提交失败，网络/API错误）
        └────┬─────┘          └──────────┘
             │
    ┌────────┴────────┐
    ▼                 ▼
┌─────────┐     ┌───────────┐
│ PARTIAL │     │ CANCELLED │  （用户撤单/风控撤单）
│（部分成）│     └───────────┘
└────┬────┘
     │ 全部成交
     ▼
┌────────┐
│ FILLED │  （最终状态）
└────────┘

注意：FILLED 和 CANCELLED 是终态，不可再变更
```

---

## 3. BaseTrader 抽象接口

```python
# backend/app/trade/base_trader.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime

@dataclass
class OrderRequest:
    stock_code: str
    side: str                   # BUY / SELL
    order_type: str             # MARKET / LIMIT
    quantity: int
    limit_price: Optional[float] = None
    signal_id: Optional[str] = None
    strategy_id: Optional[int] = None
    trigger_source: str = 'auto'
    operator: Optional[str] = None

@dataclass
class OrderResult:
    order_id: str
    status: str                 # SUBMITTED / FAILED
    broker_order_id: Optional[str] = None
    message: str = ""

@dataclass
class FillResult:
    order_id: str
    status: str                 # FILLED / PARTIAL / CANCELLED
    filled_quantity: int = 0
    avg_fill_price: float = 0.0
    commission: float = 0.0
    stamp_tax: float = 0.0
    filled_at: Optional[datetime] = None

@dataclass
class Position:
    stock_code: str
    total_qty: int
    available_qty: int          # T+1: 当日买入不可卖
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float

@dataclass
class AccountInfo:
    total_assets: float
    cash: float
    market_value: float
    frozen_cash: float
    daily_pnl: float
    total_pnl: float

class BaseTrader(ABC):

    @abstractmethod
    async def submit_order(self, request: OrderRequest) -> OrderResult:
        """提交订单到执行系统"""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        pass

    @abstractmethod
    async def get_order_status(self, order_id: str) -> FillResult:
        """查询订单状态"""
        pass

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """查询当前持仓"""
        pass

    @abstractmethod
    async def get_account_info(self) -> AccountInfo:
        """查询账户信息"""
        pass

    @abstractmethod
    async def sync_positions(self) -> None:
        """从券商同步持仓到本地数据库（实盘专用）"""
        pass
```

---

## 4. SimulationTrader（模拟盘）

```python
# backend/app/trade/simulation_trader.py

import uuid
from datetime import datetime, date
from .base_trader import BaseTrader, OrderRequest, OrderResult, FillResult, Position, AccountInfo

class SimulationTrader(BaseTrader):
    """
    模拟盘交易执行器
    - 使用真实历史/实时价格撮合
    - 考虑手续费、印花税、滑点
    - 实现T+1持仓限制
    - 不操作真实资金
    """

    COMMISSION_RATE = 0.0003    # 万三手续费（双边）
    STAMP_TAX_RATE = 0.0005     # 印花税（卖方单向）
    SLIPPAGE_RATE = 0.001       # 0.1%滑点（模拟冲击成本）
    MIN_COMMISSION = 5.0        # 最低手续费5元

    def __init__(self, db, data_client):
        self.db = db
        self.data = data_client
        self.mode = 'simulation'

    async def submit_order(self, request: OrderRequest) -> OrderResult:
        """
        模拟撮合：
        - MARKET单：立即以当前价（+滑点）成交
        - LIMIT单：如果当前价满足条件则成交，否则挂单等待
        """
        order_id = str(uuid.uuid4())

        # 获取当前价格
        quote = await self.data.get_quote(request.stock_code)
        if quote is None:
            return OrderResult(order_id=order_id, status='FAILED',
                               message=f'无法获取{request.stock_code}行情')

        current_price = quote['price']

        # 检查涨跌停
        limit_up = quote.get('prev_close', current_price) * 1.10
        limit_down = quote.get('prev_close', current_price) * 0.90

        if request.side == 'BUY' and current_price >= limit_up * 0.999:
            return OrderResult(order_id=order_id, status='FAILED',
                               message='涨停板，无法买入')
        if request.side == 'SELL' and current_price <= limit_down * 1.001:
            return OrderResult(order_id=order_id, status='FAILED',
                               message='跌停板，无法卖出')

        # 计算成交价（加入滑点）
        if request.order_type == 'MARKET':
            if request.side == 'BUY':
                fill_price = current_price * (1 + self.SLIPPAGE_RATE)
                fill_price = min(fill_price, limit_up)  # 不超涨停
            else:
                fill_price = current_price * (1 - self.SLIPPAGE_RATE)
                fill_price = max(fill_price, limit_down)  # 不低于跌停
        else:  # LIMIT
            if request.side == 'BUY' and current_price <= request.limit_price:
                fill_price = request.limit_price
            elif request.side == 'SELL' and current_price >= request.limit_price:
                fill_price = request.limit_price
            else:
                # 挂单未成交，记录SUBMITTED状态，后续轮询检查
                return OrderResult(order_id=order_id, status='SUBMITTED',
                                   message='限价单挂单等待成交')

        # 计算费用
        amount = fill_price * request.quantity
        commission = max(amount * self.COMMISSION_RATE, self.MIN_COMMISSION)
        stamp_tax = amount * self.STAMP_TAX_RATE if request.side == 'SELL' else 0
        total_cost = amount + commission + stamp_tax

        # 检查资金是否充足（买入时）
        if request.side == 'BUY':
            account = await self.get_account_info()
            if account.cash < total_cost:
                return OrderResult(order_id=order_id, status='FAILED',
                                   message=f'资金不足，需要¥{total_cost:.2f}，可用¥{account.cash:.2f}')

        # 检查持仓是否充足（卖出时，T+1约束）
        if request.side == 'SELL':
            position = self._get_position(request.stock_code)
            if position is None or position.available_qty < request.quantity:
                available = position.available_qty if position else 0
                return OrderResult(order_id=order_id, status='FAILED',
                                   message=f'可卖数量不足，需要{request.quantity}股，可用{available}股（T+1限制）')

        # 执行事务：更新订单+持仓+账户
        await self._execute_fill_transaction(
            order_id=order_id,
            request=request,
            fill_price=fill_price,
            quantity=request.quantity,
            commission=commission,
            stamp_tax=stamp_tax,
        )

        return OrderResult(
            order_id=order_id,
            status='SUBMITTED',
            message=f'模拟成交：{request.side} {request.quantity}股 @{fill_price:.2f}'
        )

    async def _execute_fill_transaction(
        self, order_id, request, fill_price, quantity, commission, stamp_tax
    ):
        """原子事务：订单+持仓+账户必须同时更新"""
        amount = fill_price * quantity

        with self.db.begin():
            try:
                # 1. 写入订单记录
                self.db.execute("""
                    INSERT INTO trade.orders
                    (id, idempotency_key, stock_code, signal_id, strategy_id,
                     side, order_type, quantity, limit_price, filled_quantity,
                     avg_fill_price, commission, status, mode,
                     trigger_source, operator, submitted_at, filled_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            'FILLED', %s, %s, %s, NOW(), NOW())
                """, [
                    order_id,
                    f"{request.signal_id}:{request.stock_code}:{request.side}:{quantity}",
                    request.stock_code, request.signal_id, request.strategy_id,
                    request.side, request.order_type, quantity, request.limit_price,
                    quantity, fill_price, commission, self.mode,
                    request.trigger_source, request.operator
                ])

                # 2. 更新持仓
                if request.side == 'BUY':
                    self._update_position_buy(request.stock_code, quantity, fill_price, amount)
                else:
                    self._update_position_sell(request.stock_code, quantity, fill_price, amount)

                # 3. 更新账户资金
                if request.side == 'BUY':
                    self.db.execute("""
                        UPDATE trade.account_records
                        SET cash = cash - %s,
                            market_value = market_value + %s,
                            record_time = NOW()
                        WHERE mode = %s
                    """, [amount + commission, amount, self.mode])
                else:
                    net_proceeds = amount - commission - stamp_tax
                    self.db.execute("""
                        UPDATE trade.account_records
                        SET cash = cash + %s,
                            market_value = market_value - %s,
                            record_time = NOW()
                        WHERE mode = %s
                    """, [net_proceeds, amount, self.mode])

                # 4. 记录订单历史
                self.db.execute("""
                    INSERT INTO trade.order_history
                    (order_id, from_status, to_status, changed_by)
                    VALUES (%s, 'PENDING', 'FILLED', 'simulation_engine')
                """, [order_id])

                self.db.commit()

            except Exception as e:
                self.db.rollback()
                raise RuntimeError(f"Fill transaction failed: {e}")

    def _update_position_buy(self, stock_code, quantity, fill_price, amount):
        """更新持仓（买入）- 移动加权平均成本"""
        existing = self._get_position(stock_code)
        if existing:
            new_qty = existing.total_qty + quantity
            new_cost = (existing.total_qty * existing.avg_cost + amount) / new_qty
            self.db.execute("""
                UPDATE trade.positions
                SET total_qty = %s,
                    avg_cost = %s,
                    total_cost = total_cost + %s,
                    updated_at = NOW()
                WHERE stock_code = %s AND mode = %s
            """, [new_qty, new_cost, amount, stock_code, self.mode])
        else:
            self.db.execute("""
                INSERT INTO trade.positions
                (stock_code, mode, total_qty, available_qty, avg_cost, total_cost)
                VALUES (%s, %s, %s, 0, %s, %s)
            """, [stock_code, self.mode, quantity, fill_price, amount])
            # 注意：available_qty=0，因为T+1，当日买入不可卖

    def _update_position_sell(self, stock_code, quantity, fill_price, amount):
        """更新持仓（卖出）"""
        existing = self._get_position(stock_code)
        if not existing:
            raise ValueError(f"持仓不存在：{stock_code}")

        realized_pnl = (fill_price - existing.avg_cost) * quantity
        new_qty = existing.total_qty - quantity
        new_available = existing.available_qty - quantity

        if new_qty == 0:
            self.db.execute("""
                DELETE FROM trade.positions
                WHERE stock_code = %s AND mode = %s
            """, [stock_code, self.mode])
        else:
            self.db.execute("""
                UPDATE trade.positions
                SET total_qty = %s,
                    available_qty = %s,
                    total_cost = avg_cost * %s,
                    realized_pnl = realized_pnl + %s,
                    updated_at = NOW()
                WHERE stock_code = %s AND mode = %s
            """, [new_qty, new_available, new_qty, realized_pnl, stock_code, self.mode])

    def _get_position(self, stock_code) -> Optional[Position]:
        row = self.db.query("""
            SELECT * FROM trade.positions
            WHERE stock_code = %s AND mode = %s
        """, [stock_code, self.mode]).fetchone()
        if not row: return None
        return Position(**dict(row))

    async def cancel_order(self, order_id: str) -> bool:
        updated = self.db.execute("""
            UPDATE trade.orders
            SET status = 'CANCELLED', cancelled_at = NOW()
            WHERE id = %s AND status IN ('PENDING', 'SUBMITTED')
        """, [order_id]).rowcount
        self.db.commit()
        return updated > 0

    async def get_order_status(self, order_id: str) -> FillResult:
        row = self.db.query("""
            SELECT * FROM trade.orders WHERE id = %s
        """, [order_id]).fetchone()
        if not row: raise ValueError(f"Order not found: {order_id}")
        return FillResult(
            order_id=order_id,
            status=row['status'],
            filled_quantity=row['filled_quantity'],
            avg_fill_price=row['avg_fill_price'] or 0,
            commission=row['commission'],
            filled_at=row['filled_at']
        )

    async def get_positions(self):
        rows = self.db.query("""
            SELECT p.*, q.price as current_price
            FROM trade.positions p
            LEFT JOIN market.quotes q ON p.stock_code = q.stock_code
                AND q.time = (SELECT MAX(time) FROM market.quotes WHERE stock_code = p.stock_code)
            WHERE p.mode = %s
        """, [self.mode]).fetchall()
        result = []
        for row in rows:
            current_price = row['current_price'] or row['avg_cost']
            market_value = current_price * row['total_qty']
            pnl = market_value - row['total_cost']
            result.append(Position(
                stock_code=row['stock_code'],
                total_qty=row['total_qty'],
                available_qty=row['available_qty'],
                avg_cost=row['avg_cost'],
                current_price=current_price,
                market_value=market_value,
                unrealized_pnl=pnl,
                unrealized_pnl_pct=pnl / row['total_cost'] if row['total_cost'] > 0 else 0
            ))
        return result

    async def get_account_info(self) -> AccountInfo:
        row = self.db.query("""
            SELECT * FROM trade.account_records
            WHERE mode = %s ORDER BY record_time DESC LIMIT 1
        """, [self.mode]).fetchone()
        if not row:
            return AccountInfo(total_assets=0, cash=0, market_value=0,
                               frozen_cash=0, daily_pnl=0, total_pnl=0)
        return AccountInfo(**dict(row))

    async def sync_positions(self):
        """模拟盘不需要同步（数据库即是真实来源）"""
        pass
```

---

## 5. QMTTrader（实盘）

```python
# backend/app/trade/qmt_trader.py

"""
QMT（迅投极速交易终端）实盘接入
注意：
1. QMT SDK 只能在 Windows 环境运行
2. 实盘模式启用前必须完成所有前置验证
3. 每次操作都必须二次确认风控
"""

from .base_trader import BaseTrader, OrderRequest, OrderResult, FillResult, Position, AccountInfo
from typing import List

class QMTTrader(BaseTrader):
    """
    QMT实盘交易接口
    通过 xtquant 库与 QMT 客户端通信
    """

    def __init__(self, db, config: dict):
        self.db = db
        self.account_id = config['qmt_account_id']
        self.path = config.get('qmt_path', 'C:/国金证券QMT交易端/userdata_mini')
        self._xt_trader = None
        self.mode = 'live'

    def _get_trader(self):
        """懒加载QMT连接（只在实盘模式下初始化）"""
        if self._xt_trader is None:
            try:
                from xtquant.xttrader import XtQuantTrader
                from xtquant.xttype import StockAccount
                self._xt_trader = XtQuantTrader(self.path, session_id=1)
                account = StockAccount(self.account_id)
                result = self._xt_trader.connect()
                if result != 0:
                    raise ConnectionError(f"QMT连接失败，错误码：{result}")
                self._xt_trader.subscribe(account)
            except ImportError:
                raise RuntimeError("xtquant未安装，实盘模式需要Windows环境和QMT客户端")
        return self._xt_trader

    async def submit_order(self, request: OrderRequest) -> OrderResult:
        """
        提交实盘订单
        注意：实盘下单前额外增加一次风控确认
        """
        import asyncio

        # 实盘额外检查：确认当前不处于熔断状态
        from app.risk.fuse import FuseManager
        fuse = FuseManager(self.db, None)
        if fuse.is_fused('live'):
            return OrderResult(
                order_id='', status='FAILED',
                message='系统处于熔断状态，所有实盘交易已暂停'
            )

        try:
            trader = self._get_trader()
            from xtquant.xttype import StockAccount

            account = StockAccount(self.account_id)

            # QMT下单
            if request.order_type == 'MARKET':
                order_type = 23  # 市价单（最优五档即时成交剩余撤销）
                price = 0
            else:
                order_type = 11  # 限价单
                price = request.limit_price

            side_code = 23 if request.side == 'BUY' else 24  # 23=买入，24=卖出

            # 在线程池中执行（QMT SDK是同步的）
            broker_order_id = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: trader.order_stock(
                    account=account,
                    stock_code=request.stock_code,
                    order_type=side_code,
                    order_volume=request.quantity,
                    price_type=order_type,
                    price=price,
                    strategy_name='AI_Quant_Trader',
                    order_remark=f"signal:{request.signal_id or 'manual'}"
                )
            )

            if broker_order_id == -1:
                return OrderResult(order_id='', status='FAILED',
                                   message='QMT下单失败，请检查QMT客户端状态')

            # 写入本地数据库
            order_id = self._save_live_order(request, broker_order_id)

            return OrderResult(
                order_id=order_id,
                status='SUBMITTED',
                broker_order_id=str(broker_order_id),
                message=f'实盘订单已提交，券商订单号：{broker_order_id}'
            )

        except Exception as e:
            return OrderResult(order_id='', status='FAILED', message=str(e))

    async def cancel_order(self, order_id: str) -> bool:
        import asyncio
        # 获取券商订单ID
        row = self.db.query("""
            SELECT broker_order_id FROM trade.orders WHERE id = %s
        """, [order_id]).fetchone()
        if not row: return False

        trader = self._get_trader()
        from xtquant.xttype import StockAccount
        account = StockAccount(self.account_id)

        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: trader.cancel_order_stock(account, int(row['broker_order_id']))
        )
        return result == 0

    async def get_positions(self) -> List[Position]:
        import asyncio
        trader = self._get_trader()
        from xtquant.xttype import StockAccount
        account = StockAccount(self.account_id)

        positions = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: trader.query_stock_positions(account)
        )

        result = []
        for p in (positions or []):
            result.append(Position(
                stock_code=p.stock_code,
                total_qty=p.volume,
                available_qty=p.can_use_volume,
                avg_cost=p.open_price,
                current_price=p.market_value / p.volume if p.volume > 0 else p.open_price,
                market_value=p.market_value,
                unrealized_pnl=p.profit,
                unrealized_pnl_pct=p.profit_rate
            ))
        return result

    async def get_account_info(self) -> AccountInfo:
        import asyncio
        trader = self._get_trader()
        from xtquant.xttype import StockAccount
        account = StockAccount(self.account_id)

        info = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: trader.query_stock_asset(account)
        )

        return AccountInfo(
            total_assets=info.total_asset,
            cash=info.cash,
            market_value=info.market_value,
            frozen_cash=info.frozen_cash,
            daily_pnl=info.profit,
            total_pnl=info.total_profit if hasattr(info, 'total_profit') else 0
        )

    async def sync_positions(self):
        """
        从QMT同步实盘持仓到本地数据库
        每次开盘前和收盘后执行
        """
        live_positions = await self.get_positions()
        live_account = await self.get_account_info()

        with self.db.begin():
            # 清空本地实盘持仓，以券商数据为准
            self.db.execute("DELETE FROM trade.positions WHERE mode = 'live'")

            for pos in live_positions:
                self.db.execute("""
                    INSERT INTO trade.positions
                    (stock_code, mode, total_qty, available_qty, avg_cost,
                     total_cost, current_price, market_value, unrealized_pnl)
                    VALUES (%s, 'live', %s, %s, %s, %s, %s, %s, %s)
                """, [
                    pos.stock_code, pos.total_qty, pos.available_qty,
                    pos.avg_cost, pos.avg_cost * pos.total_qty,
                    pos.current_price, pos.market_value, pos.unrealized_pnl
                ])

            # 更新账户记录
            self.db.execute("""
                INSERT INTO trade.account_records
                (mode, total_assets, cash, market_value, frozen_cash, daily_pnl, data_type)
                VALUES ('live', %s, %s, %s, %s, %s, 'sync')
                ON CONFLICT (mode) DO UPDATE SET
                    total_assets = EXCLUDED.total_assets,
                    cash = EXCLUDED.cash,
                    market_value = EXCLUDED.market_value,
                    frozen_cash = EXCLUDED.frozen_cash,
                    daily_pnl = EXCLUDED.daily_pnl,
                    record_time = NOW()
            """, [
                live_account.total_assets, live_account.cash,
                live_account.market_value, live_account.frozen_cash,
                live_account.daily_pnl
            ])

            self.db.commit()

    def _save_live_order(self, request: OrderRequest, broker_order_id) -> str:
        import uuid
        order_id = str(uuid.uuid4())
        self.db.execute("""
            INSERT INTO trade.orders
            (id, idempotency_key, stock_code, signal_id, strategy_id,
             side, order_type, quantity, limit_price, status, mode,
             trigger_source, operator, broker_order_id, submitted_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'SUBMITTED', 'live',
                    %s, %s, %s, NOW())
        """, [
            order_id,
            f"{request.signal_id}:{request.stock_code}:{request.side}:{request.quantity}",
            request.stock_code, request.signal_id, request.strategy_id,
            request.side, request.order_type, request.quantity, request.limit_price,
            request.trigger_source, request.operator, str(broker_order_id)
        ])
        self.db.commit()
        return order_id

    async def get_order_status(self, order_id: str) -> FillResult:
        # 从本地DB查，通过回调机制更新
        row = self.db.query("SELECT * FROM trade.orders WHERE id = %s", [order_id]).fetchone()
        if not row: raise ValueError(f"Order {order_id} not found")
        return FillResult(
            order_id=order_id,
            status=row['status'],
            filled_quantity=row['filled_quantity'] or 0,
            avg_fill_price=row['avg_fill_price'] or 0,
            commission=row['commission'] or 0,
            filled_at=row['filled_at']
        )
```

---

## 6. OrderManager（订单管理器）

```python
# backend/app/trade/order_manager.py

class OrderManager:
    """
    订单生命周期管理
    所有交易必须通过OrderManager，不能直接调用Trader
    """

    def __init__(self, db, risk_checker, fuse_manager, ws_manager, traders: dict):
        self.db = db
        self.risk = risk_checker
        self.fuse = fuse_manager
        self.ws = ws_manager
        self.traders = traders  # {'simulation': SimulationTrader, 'paper': PaperTrader, 'live': QMTTrader}

    async def create_order(self, request: OrderRequest, mode: str) -> dict:
        """
        创建并执行订单
        完整流程：幂等检查 → 熔断检查 → 风控检查 → 执行 → 推送
        """
        # Step 0: 系统模式检查
        if mode == 'live':
            import os
            if os.getenv('TRADE_MODE') != 'live':
                return {'success': False, 'message': '系统未开启实盘模式，请在.env中配置TRADE_MODE=live'}

        # Step 1: 幂等检查
        idempotency_key = f"{request.signal_id}:{request.stock_code}:{request.side}:{request.quantity}"
        existing = self.db.query("""
            SELECT id, status FROM trade.orders
            WHERE idempotency_key = %s AND mode = %s
        """, [idempotency_key, mode]).fetchone()

        if existing:
            return {
                'success': True,
                'order_id': existing['id'],
                'message': f'重复请求，返回已有订单 {existing["id"]} (状态:{existing["status"]})',
                'idempotent': True
            }

        # Step 2: 熔断检查
        if self.fuse.is_fused(mode):
            return {'success': False, 'message': f'{mode}模式处于熔断状态，所有交易已暂停'}

        # Step 3: 风控检查
        risk_report = self.risk.check(request.__dict__, mode)
        if not risk_report.passed:
            return {
                'success': False,
                'message': f'风控拦截: {", ".join(risk_report.blocked_by)}',
                'risk_report': risk_report.__dict__
            }

        # Step 4: 执行订单
        trader = self.traders.get(mode)
        if not trader:
            return {'success': False, 'message': f'不支持的交易模式: {mode}'}

        result = await trader.submit_order(request)

        # Step 5: WebSocket推送
        await self.ws.broadcast('portfolio', {
            'type': 'order_update',
            'order_id': result.order_id,
            'status': result.status,
            'stock_code': request.stock_code,
            'side': request.side,
            'quantity': request.quantity,
            'message': result.message,
        })

        return {
            'success': result.status != 'FAILED',
            'order_id': result.order_id,
            'status': result.status,
            'message': result.message,
            'warnings': risk_report.warnings,
        }
```

---

## 7. 资金对账机制

```python
# backend/app/trade/reconciliation.py

"""
对账机制：定期比对本地数据库与券商数据，发现并修复不一致
对实盘模式至关重要，确保数据准确
"""

class ReconciliationService:

    def __init__(self, db, qmt_trader, ws_manager):
        self.db = db
        self.qmt = qmt_trader
        self.ws = ws_manager

    async def reconcile_positions(self) -> dict:
        """持仓对账：比对本地DB与QMT真实持仓"""
        local_positions = self._get_local_positions('live')
        broker_positions = await self.qmt.get_positions()

        issues = []
        broker_map = {p.stock_code: p for p in broker_positions}
        local_map = {code: pos for code, pos in local_positions.items()}

        # 检查本地有但券商没有的持仓
        for code in local_map:
            if code not in broker_map:
                issues.append({
                    'type': 'GHOST_POSITION',
                    'stock_code': code,
                    'local_qty': local_map[code]['total_qty'],
                    'broker_qty': 0,
                    'severity': 'CRITICAL'
                })

        # 检查券商有但本地没有的持仓
        for code in broker_map:
            if code not in local_map:
                issues.append({
                    'type': 'MISSING_POSITION',
                    'stock_code': code,
                    'local_qty': 0,
                    'broker_qty': broker_map[code].total_qty,
                    'severity': 'CRITICAL'
                })

        # 检查数量不一致
        for code in set(local_map) & set(broker_map):
            local_qty = local_map[code]['total_qty']
            broker_qty = broker_map[code].total_qty
            if local_qty != broker_qty:
                issues.append({
                    'type': 'QTY_MISMATCH',
                    'stock_code': code,
                    'local_qty': local_qty,
                    'broker_qty': broker_qty,
                    'diff': broker_qty - local_qty,
                    'severity': 'ERROR'
                })

        if issues:
            # 记录对账问题
            self._log_reconciliation_issues(issues)

            # 推送告警
            await self.ws.broadcast('alerts', {
                'type': 'reconciliation_issue',
                'level': 'CRITICAL',
                'count': len(issues),
                'message': f'持仓对账发现{len(issues)}处不一致，请立即检查',
                'issues': issues
            })

            # 自动修复（以券商数据为准）
            await self.qmt.sync_positions()

        return {
            'reconciled_at': datetime.utcnow().isoformat(),
            'issues_found': len(issues),
            'issues': issues,
            'auto_fixed': len(issues) > 0
        }

    async def reconcile_account(self) -> dict:
        """账户资金对账"""
        local_account = self._get_local_account('live')
        broker_account = await self.qmt.get_account_info()

        issues = []
        tolerance = 1.0  # 1元误差容忍

        if abs(local_account['cash'] - broker_account.cash) > tolerance:
            issues.append({
                'field': 'cash',
                'local': local_account['cash'],
                'broker': broker_account.cash,
                'diff': broker_account.cash - local_account['cash']
            })

        if abs(local_account['total_assets'] - broker_account.total_assets) > tolerance:
            issues.append({
                'field': 'total_assets',
                'local': local_account['total_assets'],
                'broker': broker_account.total_assets,
                'diff': broker_account.total_assets - local_account['total_assets']
            })

        if issues:
            self._log_reconciliation_issues(issues)
            # 以券商为准自动修复
            self._update_account_from_broker(broker_account)

        return {'issues': issues, 'auto_fixed': len(issues) > 0}

    def _get_local_positions(self, mode): ...
    def _get_local_account(self, mode): ...
    def _log_reconciliation_issues(self, issues): ...
    def _update_account_from_broker(self, account): ...
```

---

## 8. T+1 每日持仓可用量更新

```python
# worker/tasks/market.py

@celery_app.task(name='tasks.update_available_quantity')
def update_available_quantity():
    """
    每日开盘前（09:25）执行：
    将昨日买入但available_qty=0的持仓更新为可卖状态（T+1）
    """
    from app.db import get_db_session
    with get_db_session() as db:
        # 将所有模拟盘/纸盘的持仓available_qty更新为total_qty
        # （昨日买入，今日可卖）
        result = db.execute("""
            UPDATE trade.positions
            SET available_qty = total_qty,
                updated_at = NOW()
            WHERE mode IN ('simulation', 'paper')
              AND available_qty < total_qty
        """)
        db.commit()
        print(f"T+1 更新：{result.rowcount} 个持仓的可卖数量已更新")

    # 实盘的T+1由券商系统自动处理，sync后会自动正确
```
