# 39-41 — 后端API完整设计

---

## 1. API设计原则

```
版本控制:  所有API以 /api/v1/ 开头，为未来版本升级预留空间
认证:      JWT Token（开发阶段可关闭，生产必须开启）
限流:      每IP每分钟100次，AI分析接口每分钟10次
响应格式:  统一 {success, data, message, timestamp}
错误码:    HTTP状态码 + 业务错误码
```

---

## 2. 统一响应格式

```python
# backend/app/core/response.py

from pydantic import BaseModel
from typing import Any, Optional
from datetime import datetime

class APIResponse(BaseModel):
    success: bool = True
    data: Any = None
    message: str = "OK"
    timestamp: str = ""
    error_code: Optional[str] = None

    def __init__(self, **data):
        if 'timestamp' not in data:
            data['timestamp'] = datetime.utcnow().isoformat()
        super().__init__(**data)

def ok(data=None, message="OK") -> APIResponse:
    return APIResponse(success=True, data=data, message=message)

def error(message: str, code: str = None, status_code: int = 400):
    from fastapi import HTTPException
    raise HTTPException(
        status_code=status_code,
        detail=APIResponse(success=False, message=message, error_code=code).dict()
    )
```

---

## 3. FastAPI 主入口

```python
# backend/app/main.py

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import time

from app.api import stock, ai, screener, strategy, backtest, risk, trade, portfolio, ws
from app.core.config import settings

app = FastAPI(
    title="AI Quant Trader Pro API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 请求耗时日志
@app.middleware("http")
async def log_request_time(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    response.headers["X-Process-Time"] = str(round(duration * 1000, 2))
    if duration > 2.0:  # 超过2秒记录慢请求
        import logging
        logging.warning(f"SLOW REQUEST: {request.method} {request.url.path} took {duration:.2f}s")
    return response

# 路由注册
app.include_router(stock.router,     prefix="/api/v1/stock",     tags=["股票数据"])
app.include_router(ai.router,        prefix="/api/v1/ai",         tags=["AI分析"])
app.include_router(screener.router,  prefix="/api/v1/screener",   tags=["选股"])
app.include_router(strategy.router,  prefix="/api/v1/strategy",   tags=["策略管理"])
app.include_router(backtest.router,  prefix="/api/v1/backtest",   tags=["回测"])
app.include_router(risk.router,      prefix="/api/v1/risk",       tags=["风控"])
app.include_router(trade.router,     prefix="/api/v1/trade",      tags=["交易"])
app.include_router(portfolio.router, prefix="/api/v1/portfolio",  tags=["持仓资产"])
app.include_router(ws.router,        prefix="/ws",                tags=["WebSocket"])

@app.get("/api/v1/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}
```

---

## 4. 完整API路由实现

### 4.1 股票数据 API

```python
# backend/app/api/stock.py

from fastapi import APIRouter, Query, Depends
from app.services.stock_service import StockService
from app.core.response import ok

router = APIRouter()

@router.get("/list")
async def get_stock_list(
    market: str = Query(None, description="SH/SZ/BJ"),
    sector: str = Query(None, description="行业筛选"),
    board: str = Query(None, description="主板/创业板/科创板"),
    keyword: str = Query(None, description="名称/代码搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, le=200),
    svc: StockService = Depends()
):
    """获取股票列表（支持筛选和搜索）"""
    result = await svc.get_stock_list(
        market=market, sector=sector, board=board,
        keyword=keyword, page=page, page_size=page_size
    )
    return ok(result)

@router.get("/{code}/profile")
async def get_stock_profile(code: str, svc: StockService = Depends()):
    """股票基础信息（名称、行业、市值、上市日期等）"""
    return ok(await svc.get_profile(code))

@router.get("/{code}/quote")
async def get_realtime_quote(code: str, svc: StockService = Depends()):
    """实时报价（价格、涨跌、买卖盘）"""
    return ok(await svc.get_quote(code))

@router.get("/{code}/kline")
async def get_kline(
    code: str,
    period: str = Query("1d", description="1min/5min/15min/30min/60min/1d/1w"),
    limit: int = Query(200, le=1000),
    adj: str = Query("qfq", description="前复权qfq/后复权hfq/不复权none"),
    svc: StockService = Depends()
):
    """K线数据"""
    return ok(await svc.get_kline(code, period, limit, adj))

@router.get("/{code}/fund-flow")
async def get_fund_flow(
    code: str,
    days: int = Query(10, le=90),
    svc: StockService = Depends()
):
    """资金流向（主力/超大单/大单净流入）"""
    return ok(await svc.get_fund_flow(code, days))

@router.get("/{code}/news")
async def get_news(
    code: str,
    limit: int = Query(20, le=100),
    svc: StockService = Depends()
):
    """相关新闻"""
    return ok(await svc.get_news(code, limit))

@router.get("/{code}/announcements")
async def get_announcements(
    code: str,
    category: str = Query(None),
    limit: int = Query(20),
    svc: StockService = Depends()
):
    """公告列表"""
    return ok(await svc.get_announcements(code, category, limit))

@router.get("/{code}/financial-report")
async def get_financial_report(code: str, svc: StockService = Depends()):
    """最新财务报告（按publish_date获取最新已发布报告）"""
    return ok(await svc.get_latest_financial_report(code))

@router.get("/{code}/holders")
async def get_holders(code: str, svc: StockService = Depends()):
    """股东数据（前十大+机构持仓）"""
    return ok(await svc.get_holders(code))

@router.get("/{code}/dragon-tiger")
async def get_dragon_tiger(code: str, svc: StockService = Depends()):
    """龙虎榜数据"""
    return ok(await svc.get_dragon_tiger(code))

@router.get("/{code}/north-flow")
async def get_north_flow(code: str, svc: StockService = Depends()):
    """北向资金（沪深港通）"""
    return ok(await svc.get_north_flow(code))

@router.get("/market/sectors")
async def get_sector_performance(svc: StockService = Depends()):
    """全市场行业板块今日表现"""
    return ok(await svc.get_sector_performance())
```

### 4.2 AI分析 API

```python
# backend/app/api/ai.py

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from app.services.ai_service import AIService
from app.core.response import ok

router = APIRouter()

@router.post("/{code}/analyze")
async def analyze_stock(
    code: str,
    background_tasks: BackgroundTasks,
    force_refresh: bool = Query(False, description="强制重新分析（忽略缓存）"),
    svc: AIService = Depends()
):
    """
    触发完整AI分析（4个Agent并发）
    有效期内直接返回缓存结果，force_refresh=True可强制刷新
    """
    # 检查是否有有效的缓存信号
    cached = await svc.get_valid_signal(code)
    if cached and not force_refresh:
        return ok(cached, "返回缓存信号")

    # 执行分析（同步，等待结果）
    signal = await svc.analyze(code)
    return ok(signal)

@router.get("/{code}/latest-signal")
async def get_latest_signal(code: str, svc: AIService = Depends()):
    """获取股票最新AI信号（不触发新分析）"""
    return ok(await svc.get_latest_signal(code))

@router.get("/signals")
async def list_signals(
    action: str = Query(None, description="BUY/SELL/HOLD"),
    min_confidence: float = Query(0.0, ge=0, le=1),
    risk_level: str = Query(None),
    limit: int = Query(50, le=200),
    svc: AIService = Depends()
):
    """最新信号列表"""
    return ok(await svc.list_signals(action, min_confidence, risk_level, limit))

@router.get("/{code}/signal-history")
async def get_signal_history(
    code: str,
    days: int = Query(30, le=365),
    svc: AIService = Depends()
):
    """历史信号记录（含执行结果）"""
    return ok(await svc.get_signal_history(code, days))

@router.post("/portfolio-advice")
async def get_portfolio_advice(
    request: dict,
    svc: AIService = Depends()
):
    """基于当前持仓获取AI组合建议"""
    return ok(await svc.get_portfolio_advice(request))
```

### 4.3 回测 API

```python
# backend/app/api/backtest.py

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import date
from app.services.backtest_service import BacktestService
from app.core.response import ok

router = APIRouter()

class BacktestRequest(BaseModel):
    strategy_id: int = None
    strategy_type: str          # ma_crossover / macd / ai_driven / hybrid
    strategy_config: dict
    universe: str = "hs300"     # hs300 / zz500 / all / custom
    custom_stocks: list = []    # universe=custom时指定
    start_date: date
    end_date: date
    initial_cash: float = 1_000_000
    enable_walk_forward: bool = False
    walk_forward_config: dict = None

class WalkForwardRequest(BaseModel):
    strategy_type: str
    param_space: dict
    universe: str = "hs300"
    start_date: date
    end_date: date
    initial_cash: float = 1_000_000
    train_months: int = 12
    oos_months: int = 3

@router.post("/run")
async def run_backtest(
    request: BacktestRequest,
    svc: BacktestService = Depends()
):
    """
    启动回测任务（异步执行）
    返回task_id，通过 GET /backtest/{task_id}/status 轮询进度
    """
    task_id = await svc.start_backtest_task(request.dict())
    return ok({'task_id': task_id, 'message': '回测任务已提交，请通过task_id查询进度'})

@router.get("/{task_id}/status")
async def get_backtest_status(task_id: int, svc: BacktestService = Depends()):
    """查询回测任务进度（0-100%）"""
    return ok(await svc.get_task_status(task_id))

@router.get("/{task_id}/result")
async def get_backtest_result(task_id: int, svc: BacktestService = Depends()):
    """获取完整回测结果（完成后可用）"""
    result = await svc.get_task_result(task_id)
    if not result:
        raise HTTPException(404, "回测未完成或任务不存在")
    return ok(result)

@router.post("/walk-forward")
async def run_walk_forward(
    request: WalkForwardRequest,
    svc: BacktestService = Depends()
):
    """启动Walk-Forward验证（比普通回测更耗时，通常需要10-30分钟）"""
    task_id = await svc.start_walk_forward_task(request.dict())
    return ok({'task_id': task_id, 'message': 'Walk-Forward任务已提交'})

@router.get("/history")
async def get_backtest_history(
    limit: int = 20,
    svc: BacktestService = Depends()
):
    """历史回测列表"""
    return ok(await svc.list_tasks(limit))

@router.delete("/{task_id}")
async def cancel_backtest(task_id: int, svc: BacktestService = Depends()):
    """取消运行中的回测"""
    return ok(await svc.cancel_task(task_id))
```

### 4.4 风控 API

```python
# backend/app/api/risk.py

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.services.risk_service import RiskService
from app.core.response import ok

router = APIRouter()

@router.get("/status")
async def get_risk_status(mode: str = "simulation", svc: RiskService = Depends()):
    """当前风控状态（是否熔断、各指标使用率）"""
    return ok(await svc.get_status(mode))

@router.get("/rules")
async def get_risk_rules(svc: RiskService = Depends()):
    """获取所有风控规则"""
    return ok(await svc.get_all_rules())

@router.put("/rules/{rule_code}")
async def update_risk_rule(
    rule_code: str,
    body: dict,
    svc: RiskService = Depends()
):
    """
    修改风控规则参数
    注意：只能调整阈值，不能删除硬约束规则
    """
    return ok(await svc.update_rule(rule_code, body))

@router.get("/events")
async def get_risk_events(
    days: int = 7,
    rule_code: str = None,
    limit: int = 100,
    svc: RiskService = Depends()
):
    """风控触发事件记录"""
    return ok(await svc.get_events(days, rule_code, limit))

@router.get("/fuse-status")
async def get_fuse_status(mode: str = "simulation", svc: RiskService = Depends()):
    """熔断状态详情"""
    return ok(await svc.get_fuse_status(mode))

@router.post("/fuse/recover")
async def recover_from_fuse(
    body: dict,     # {mode, approved_by, note}
    svc: RiskService = Depends()
):
    """
    人工审批后解除熔断
    必须提供审批人和备注，记录到审计日志
    """
    return ok(await svc.recover_fuse(
        mode=body['mode'],
        approved_by=body['approved_by'],
        note=body.get('note', '')
    ))

@router.get("/var")
async def get_var(
    mode: str = "simulation",
    confidence: float = 0.95,
    horizon: int = 1,
    svc: RiskService = Depends()
):
    """当前持仓的VaR（风险价值）计算"""
    return ok(await svc.calculate_var(mode, confidence, horizon))
```

### 4.5 交易 API

```python
# backend/app/api/trade.py

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from app.services.trade_service import TradeService
from app.core.response import ok, error

router = APIRouter()

class OrderCreateRequest(BaseModel):
    stock_code: str
    side: str                       # BUY / SELL
    order_type: str = "LIMIT"       # MARKET / LIMIT
    quantity: int
    limit_price: Optional[float] = None
    signal_id: Optional[str] = None
    mode: str = "simulation"        # simulation / paper / live

@router.post("/order")
async def create_order(
    request: OrderCreateRequest,
    svc: TradeService = Depends()
):
    """
    手动下单
    经过完整风控检查后执行
    """
    if request.quantity <= 0 or request.quantity % 100 != 0:
        error("买入数量必须是100的整数倍", "INVALID_QUANTITY")

    if request.order_type == 'LIMIT' and not request.limit_price:
        error("限价单必须提供limit_price", "MISSING_PRICE")

    result = await svc.create_manual_order(request.dict())
    return ok(result)

@router.delete("/order/{order_id}")
async def cancel_order(
    order_id: str,
    mode: str = "simulation",
    svc: TradeService = Depends()
):
    """撤销订单（只能撤销PENDING/SUBMITTED状态的订单）"""
    return ok(await svc.cancel_order(order_id, mode))

@router.get("/orders")
async def list_orders(
    mode: str = "simulation",
    status: str = None,
    days: int = 7,
    page: int = 1,
    page_size: int = 50,
    svc: TradeService = Depends()
):
    """订单列表"""
    return ok(await svc.list_orders(mode, status, days, page, page_size))

@router.get("/orders/{order_id}")
async def get_order(order_id: str, svc: TradeService = Depends()):
    """订单详情（含状态流转历史）"""
    return ok(await svc.get_order_detail(order_id))

@router.get("/positions")
async def get_positions(mode: str = "simulation", svc: TradeService = Depends()):
    """当前持仓（含实时盈亏）"""
    return ok(await svc.get_positions(mode))

@router.get("/account")
async def get_account(mode: str = "simulation", svc: TradeService = Depends()):
    """账户资产概览"""
    return ok(await svc.get_account_info(mode))

@router.post("/reconcile")
async def trigger_reconciliation(mode: str = "live", svc: TradeService = Depends()):
    """手动触发持仓/资金对账（实盘）"""
    return ok(await svc.reconcile(mode))

@router.get("/mode")
async def get_trade_mode(svc: TradeService = Depends()):
    """获取当前交易模式"""
    return ok(await svc.get_current_mode())
```

---

## 5. WebSocket 完整实现

### 5.1 WebSocket Manager

```python
# backend/app/ws/manager.py

from fastapi import WebSocket
from typing import Dict, List, Set
import json
import asyncio
from datetime import datetime

class WebSocketManager:
    """
    WebSocket连接管理器
    支持频道订阅模式
    """

    def __init__(self, redis_client):
        self.redis = redis_client
        # {channel: [websocket, ...]}
        self._connections: Dict[str, List[WebSocket]] = {}
        # {websocket: {channels}}
        self._client_channels: Dict[WebSocket, Set[str]] = {}

    async def connect(self, websocket: WebSocket, channel: str):
        await websocket.accept()
        if channel not in self._connections:
            self._connections[channel] = []
        self._connections[channel].append(websocket)
        if websocket not in self._client_channels:
            self._client_channels[websocket] = set()
        self._client_channels[websocket].add(channel)

    async def disconnect(self, websocket: WebSocket):
        channels = self._client_channels.pop(websocket, set())
        for channel in channels:
            if channel in self._connections:
                try:
                    self._connections[channel].remove(websocket)
                except ValueError:
                    pass

    async def broadcast(self, channel: str, data: dict):
        """向所有订阅该频道的客户端推送消息"""
        if channel not in self._connections:
            return

        message = json.dumps({
            **data,
            '_channel': channel,
            '_ts': datetime.utcnow().isoformat()
        }, ensure_ascii=False)

        dead_connections = []
        for ws in self._connections.get(channel, []):
            try:
                await ws.send_text(message)
            except Exception:
                dead_connections.append(ws)

        # 清理断开的连接
        for ws in dead_connections:
            await self.disconnect(ws)

    async def start_redis_subscriber(self):
        """订阅Redis Pub/Sub，将消息广播给WebSocket客户端"""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(
            'channel:quotes',
            'channel:signals',
            'channel:portfolio',
            'channel:alerts'
        )

        async for message in pubsub.listen():
            if message['type'] != 'message':
                continue
            try:
                channel = message['channel'].decode().replace('channel:', '')
                data = json.loads(message['data'])
                await self.broadcast(channel, data)
            except Exception as e:
                print(f"[WS Subscriber Error] {e}")
```

### 5.2 WebSocket 路由

```python
# backend/app/api/ws.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.ws.manager import WebSocketManager
from app.core.deps import get_ws_manager

router = APIRouter()

@router.websocket("/quotes/{stock_code}")
async def ws_quote(
    websocket: WebSocket,
    stock_code: str,
    manager: WebSocketManager = Depends(get_ws_manager)
):
    """
    实时行情推送
    连接后会收到该股票的行情更新（每3秒）
    消息格式：{"type":"quote","code":"000001","price":...}
    """
    channel = f"quotes:{stock_code}"
    await manager.connect(websocket, channel)
    try:
        while True:
            # 保持连接，等待服务端推送
            # 客户端需定期发送 ping 保持活跃
            data = await websocket.receive_text()
            if data == 'ping':
                await websocket.send_text('pong')
    except WebSocketDisconnect:
        await manager.disconnect(websocket)

@router.websocket("/signals")
async def ws_signals(
    websocket: WebSocket,
    manager: WebSocketManager = Depends(get_ws_manager)
):
    """
    AI信号实时推送
    有新信号产生时立即推送
    """
    await manager.connect(websocket, 'signals')
    try:
        while True:
            data = await websocket.receive_text()
            if data == 'ping':
                await websocket.send_text('pong')
    except WebSocketDisconnect:
        await manager.disconnect(websocket)

@router.websocket("/portfolio")
async def ws_portfolio(
    websocket: WebSocket,
    mode: str = Query("simulation"),
    manager: WebSocketManager = Depends(get_ws_manager)
):
    """
    持仓实时更新推送
    有订单成交或持仓市值变化时推送
    """
    await manager.connect(websocket, f"portfolio:{mode}")
    try:
        while True:
            data = await websocket.receive_text()
            if data == 'ping':
                await websocket.send_text('pong')
    except WebSocketDisconnect:
        await manager.disconnect(websocket)

@router.websocket("/alerts")
async def ws_alerts(
    websocket: WebSocket,
    manager: WebSocketManager = Depends(get_ws_manager)
):
    """
    风控告警实时推送
    熔断、预警、对账异常等立即推送
    """
    await manager.connect(websocket, 'alerts')
    try:
        while True:
            data = await websocket.receive_text()
            if data == 'ping':
                await websocket.send_text('pong')
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
```

### 5.3 WebSocket 消息协议

```typescript
// 前端接收的消息格式

// 行情推送
interface QuoteMessage {
  type: 'quote';
  code: string;
  name: string;
  price: number;
  open: number;
  high: number;
  low: number;
  prev_close: number;
  change: number;
  change_pct: number;
  volume: number;
  amount: number;
  _channel: string;
  _ts: string;
}

// AI信号推送
interface SignalMessage {
  type: 'signal';
  id: string;
  stock_code: string;
  stock_name: string;
  action: 'BUY' | 'SELL' | 'HOLD';
  confidence: number;
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'EXTREME';
  price_at: number;
  reason: string;
  signal_time: string;
  _ts: string;
}

// 订单更新推送
interface OrderUpdateMessage {
  type: 'order_update';
  order_id: string;
  stock_code: string;
  side: 'BUY' | 'SELL';
  status: string;
  filled_quantity: number;
  avg_fill_price: number;
  _ts: string;
}

// 风控告警推送
interface AlertMessage {
  type: 'risk_alert' | 'fuse_activated' | 'reconciliation_issue';
  level: 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';
  message: string;
  detail?: any;
  _ts: string;
}
```

---

## 6. Celery 调度完整配置

```python
# worker/celery_app.py

from celery import Celery
from celery.schedules import crontab
import os

app = Celery('quant_trader')

app.config_from_object({
    'broker_url': os.getenv('CELERY_BROKER_URL'),
    'result_backend': os.getenv('CELERY_RESULT_BACKEND'),
    'task_serializer': 'json',
    'result_serializer': 'json',
    'accept_content': ['json'],
    'timezone': 'Asia/Shanghai',
    'enable_utc': True,

    # 任务队列优先级
    'task_queues': {
        'high': {'exchange': 'high', 'routing_key': 'high'},     # 实时行情同步
        'normal': {'exchange': 'normal', 'routing_key': 'normal'}, # AI分析、选股
        'low': {'exchange': 'low', 'routing_key': 'low'},         # 回测、数据归档
    },
    'task_default_queue': 'normal',

    # 任务路由
    'task_routes': {
        'tasks.sync_realtime_quotes': {'queue': 'high'},
        'tasks.sync_portfolio_value': {'queue': 'high'},
        'tasks.run_signal_scan': {'queue': 'normal'},
        'tasks.run_ai_analysis': {'queue': 'normal'},
        'tasks.morning_screening': {'queue': 'normal'},
        'tasks.run_backtest_task': {'queue': 'low'},
        'tasks.index_new_announcements': {'queue': 'low'},
        'tasks.archive_daily_data': {'queue': 'low'},
    },

    # 定时任务（Celery Beat）
    'beat_schedule': {
        # ── 交易时段（工作日09:25-15:05）──
        'sync-quotes-3s': {
            'task': 'tasks.sync_realtime_quotes',
            'schedule': 3.0,                # 每3秒
        },
        'sync-portfolio-30s': {
            'task': 'tasks.sync_portfolio_value',
            'schedule': 30.0,               # 每30秒更新持仓市值
        },
        'ai-signal-scan-1min': {
            'task': 'tasks.run_signal_scan',
            'schedule': 60.0,               # 每分钟扫描一次
        },
        'update-available-qty': {
            'task': 'tasks.update_available_quantity',
            'schedule': crontab(hour=9, minute=25),  # 开盘前T+1
        },

        # ── 每日固定时间 ──
        'morning-screening-0915': {
            'task': 'tasks.morning_screening',
            'schedule': crontab(hour=9, minute=15),
        },
        'sync-fund-flow-30min': {
            'task': 'tasks.sync_fund_flow',
            'schedule': 1800.0,             # 每30分钟
        },
        'archive-daily-data-1530': {
            'task': 'tasks.archive_daily_data',
            'schedule': crontab(hour=15, minute=30),
        },
        'sync-live-positions-1530': {
            'task': 'tasks.sync_live_positions_from_broker',
            'schedule': crontab(hour=15, minute=35),
        },
        'reconcile-accounts-1600': {
            'task': 'tasks.reconcile_accounts',
            'schedule': crontab(hour=16, minute=0),
        },
        'index-announcements-hourly': {
            'task': 'tasks.index_new_announcements',
            'schedule': crontab(minute=0),  # 每小时整点
        },

        # ── 每日收盘后 ──
        'daily-eod-snapshot': {
            'task': 'tasks.take_eod_snapshot',
            'schedule': crontab(hour=16, minute=30),
        },

        # ── 每周 ──
        'weekly-full-sync-sunday': {
            'task': 'tasks.weekly_full_data_sync',
            'schedule': crontab(day_of_week=0, hour=2, minute=0),
        },
        'weekly-backfill-check': {
            'task': 'tasks.check_kline_completeness',
            'schedule': crontab(day_of_week=0, hour=3, minute=0),
        },
    },

    # Worker配置
    'worker_max_tasks_per_child': 100,   # 防内存泄漏
    'task_soft_time_limit': 300,         # 任务5分钟软超时
    'task_time_limit': 600,              # 任务10分钟硬超时
    'task_acks_late': True,              # 任务完成后才ack（防丢失）
})
```
