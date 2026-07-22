import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import text

from app.api import (
    ai,
    auth,
    backtest,
    data,
    jobs,
    market,
    portfolio,
    research,
    risk,
    rules,
    screener,
    shadow,
    stock,
    strategy,
    system,
    trade,
    ws,
)
from app.core.auth import api_security_middleware
from app.core.config import settings
from app.core.logging import (
    FEATURE_MONITOR,
    FEATURE_SYSTEM,
    bind_request_context,
    clear_request_context,
    feature_from_path,
    get_logger,
    is_quiet_path,
    new_request_id,
    setup_logging,
)
from app.core.response import error, ok, register_exception_handlers
from app.db import engine
from app.monitoring.metrics import metrics_response, set_ws_connections
from app.ws.manager import ws_manager

log = get_logger(__name__, feature=FEATURE_SYSTEM)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_api_security_settings()
    setup_logging()
    log.info(
        "application_starting",
        env=settings.APP_ENV,
        trade_mode=settings.TRADE_MODE,
        log_level=settings.LOG_LEVEL,
    )
    if (settings.API_KEY or "").strip():
        log.warning(
            "legacy_api_key_ignored",
            hint="API_KEY 不再作为接口授权来源，请使用主体凭据或浏览器会话",
        )
    if settings.TRADE_MODE == "live" and not (settings.LIVE_CONFIRM_TOKEN or "").strip():
        log.warning(
            "live_confirm_token_missing",
            hint="TRADE_MODE=live 但未配置 LIVE_CONFIRM_TOKEN，实盘下单将被拒绝",
        )
    await ws_manager.start()
    log.info("application_ready", docs="/api/docs", health="/api/v1/health")
    yield
    await ws_manager.stop()
    try:
        from app.data.client import close_shared_http

        await close_shared_http()
    except Exception:
        pass
    await engine.dispose()
    log.info("application_shutdown")


app = FastAPI(
    title="AI Quant Trader Pro API",
    version="1.0.0",
    docs_url=None if settings.is_production() else "/api/docs",
    redoc_url=None if settings.is_production() else "/api/redoc",
    openapi_url=None if settings.is_production() else "/api/openapi.json",
    lifespan=lifespan,
)
register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def api_auth_middleware(request: Request, call_next):
    return await api_security_middleware(request, call_next)


@app.middleware("http")
async def global_request_logging(request: Request, call_next):
    """全局请求日志：request_id + 功能域 + 耗时 + 状态码。"""
    path = request.url.path
    method = request.method
    feature = feature_from_path(path)
    request_id = request.headers.get("X-Request-ID") or new_request_id()
    client = request.client.host if request.client else ""
    quiet = is_quiet_path(path)

    bind_request_context(
        request_id=request_id,
        method=method,
        path=path,
        feature=feature,
        client=client,
    )
    request.state.request_id = request_id
    request.state.feature = feature

    start = time.perf_counter()
    if not quiet:
        log.info(
            "request_start",
            feature=feature,
            method=method,
            path=path,
            query=str(request.url.query)[:200] if request.url.query else "",
        )

    response: Response | None = None
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = str(duration_ms)
        if quiet:
            log.debug(
                "request_end",
                feature=feature,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
            )
        elif status_code >= 400 or duration_ms > 2000:
            log.warning(
                "request_end",
                feature=feature,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
                slow=duration_ms > 2000,
            )
        else:
            log.info(
                "request_end",
                feature=feature,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
                slow=False,
            )
        return response
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        log.error(
            "request_exception",
            feature=feature,
            method=method,
            path=path,
            duration_ms=duration_ms,
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=True,
        )
        raise
    finally:
        clear_request_context()


app.include_router(stock.router, prefix="/api/v1/stock", tags=["股票数据"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["认证"])
app.include_router(ai.router, prefix="/api/v1/ai", tags=["AI分析"])
app.include_router(screener.router, prefix="/api/v1/screener", tags=["选股"])
app.include_router(shadow.router, prefix="/api/v1/shadow", tags=["P3-0 影子审计"])
app.include_router(strategy.router, prefix="/api/v1/strategy", tags=["策略管理"])
app.include_router(backtest.router, prefix="/api/v1/backtest", tags=["回测"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["异步任务"])
app.include_router(risk.router, prefix="/api/v1/risk", tags=["风控"])
app.include_router(trade.router, prefix="/api/v1/trade", tags=["交易"])
app.include_router(portfolio.router, prefix="/api/v1/portfolio", tags=["持仓资产"])
app.include_router(research.router, prefix="/api/v1/research", tags=["研究资格"])
app.include_router(data.router, prefix="/api/v1/data", tags=["数据认证"])
app.include_router(rules.router, prefix="/api/v1/rules", tags=["交易规则"])
app.include_router(market.router, prefix="/api/v1/market", tags=["市场状态"])
app.include_router(system.router, prefix="/api/v1/system", tags=["系统可观测性"])
app.include_router(ws.router, prefix="/ws", tags=["WebSocket"])


@app.get("/api/v1/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0", "kind": "liveness"}


@app.get("/api/v1/readiness")
async def readiness_check():
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        get_logger(__name__, feature=FEATURE_MONITOR).warning(
            "readiness_db_failed", error_type=type(exc).__name__
        )
        error(
            "数据库依赖暂时不可用",
            "READINESS_UNAVAILABLE",
            503,
            retryable=True,
        )
    return ok({"status": "ok", "checks": {"database": "ok"}})


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus scrape endpoint with scope enforcement."""
    try:
        set_ws_connections(ws_manager.connection_count)
    except Exception:
        pass
    body, content_type = metrics_response()
    return Response(content=body, media_type=content_type)
