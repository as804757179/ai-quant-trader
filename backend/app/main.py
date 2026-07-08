import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import text

from app.api import ai, backtest, portfolio, risk, screener, stock, strategy, trade, ws
from app.core.config import settings
from app.core.logging import logger, setup_logging
from app.db import engine
from app.ws.manager import ws_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("application_starting", env=settings.APP_ENV)
    await ws_manager.start()
    yield
    await ws_manager.stop()
    await engine.dispose()
    logger.info("application_shutdown")


app = FastAPI(
    title="AI Quant Trader Pro API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def log_request_time(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    response.headers["X-Process-Time"] = str(round(duration * 1000, 2))
    if duration > 2.0:
        logger.warning(
            "slow_request",
            method=request.method,
            path=request.url.path,
            duration_ms=round(duration * 1000, 2),
        )
    return response


app.include_router(stock.router, prefix="/api/v1/stock", tags=["股票数据"])
app.include_router(ai.router, prefix="/api/v1/ai", tags=["AI分析"])
app.include_router(screener.router, prefix="/api/v1/screener", tags=["选股"])
app.include_router(strategy.router, prefix="/api/v1/strategy", tags=["策略管理"])
app.include_router(backtest.router, prefix="/api/v1/backtest", tags=["回测"])
app.include_router(risk.router, prefix="/api/v1/risk", tags=["风控"])
app.include_router(trade.router, prefix="/api/v1/trade", tags=["交易"])
app.include_router(portfolio.router, prefix="/api/v1/portfolio", tags=["持仓资产"])
app.include_router(ws.router, prefix="/ws", tags=["WebSocket"])


@app.get("/api/v1/health")
async def health_check():
    checks: dict[str, str] = {"api": "ok"}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"

    status = "ok" if checks.get("database") == "ok" else "degraded"
    return {"status": status, "version": "1.0.0", "checks": checks}