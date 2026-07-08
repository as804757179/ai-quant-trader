# 05 — 基础设施完整配置

---

## 1. Docker 完整文件

### backend/Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python依赖（先复制requirements，利用Docker层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY . .

# 非root用户（安全）
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

### backend/requirements.txt

```
# Web框架
fastapi==0.109.0
uvicorn[standard]==0.27.0
python-multipart==0.0.6

# 数据库
sqlalchemy[asyncio]==2.0.25
asyncpg==0.29.0
psycopg2-binary==2.9.9
alembic==1.13.1

# 缓存/队列
redis[hiredis]==5.0.1
celery==5.3.6
redbeat==2.2.0          # 持久化Celery Beat调度

# AI模型
openai==1.10.0
anthropic==0.18.1

# 向量数据库
chromadb==0.4.22

# 数据处理
pandas==2.2.0
numpy==1.26.4
scipy==1.12.0

# 回测
backtrader==1.9.78.123
quantstats==0.0.62
optuna==3.5.0           # AutoML贝叶斯优化

# HTTP客户端
httpx==0.26.0
aiohttp==3.9.1

# 工具
pydantic==2.6.0
pydantic-settings==2.1.0
python-dotenv==1.0.1
structlog==24.1.0
prometheus-client==0.19.0
circuitbreaker==2.0.0

# 测试
pytest==7.4.4
pytest-asyncio==0.23.4
httpx==0.26.0            # 测试客户端

# PDF处理（研报提取）
pypdf==3.17.4
```

### worker/Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m worker && chown -R worker:worker /app
USER worker

CMD ["celery", "-A", "celery_app", "worker", "-Q", "high,normal,low", "--concurrency=4", "--loglevel=info"]
```

### frontend/Dockerfile

```dockerfile
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci --legacy-peer-deps

COPY . .
RUN npm run build

# 生产镜像（只包含构建产物）
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000
```

---

## 2. Nginx 配置

```nginx
# docker/nginx/nginx.conf

user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # 日志格式
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for" '
                    'rt=$request_time';
    access_log /var/log/nginx/access.log main;

    sendfile on;
    keepalive_timeout 65;
    gzip on;
    gzip_types text/plain text/css application/json application/javascript;

    # 限流
    limit_req_zone $binary_remote_addr zone=api:10m rate=100r/m;
    limit_req_zone $binary_remote_addr zone=ai_api:10m rate=10r/m;

    upstream backend {
        server api:8000;
        keepalive 32;
    }

    upstream frontend {
        server frontend:3000;
    }

    server {
        listen 80;
        server_name _;

        # 前端（React SPA）
        location / {
            proxy_pass http://frontend;
            proxy_set_header Host $host;
        }

        # 后端 REST API
        location /api/ {
            limit_req zone=api burst=20 nodelay;
            proxy_pass http://backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_read_timeout 120s;    # AI分析可能耗时较长
        }

        # AI 接口单独限流
        location /api/v1/ai/ {
            limit_req zone=ai_api burst=5 nodelay;
            proxy_pass http://backend;
            proxy_set_header Host $host;
            proxy_read_timeout 60s;
        }

        # WebSocket（关键：需要特殊配置）
        location /ws/ {
            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_read_timeout 3600s;   # WebSocket长连接
            proxy_send_timeout 3600s;
        }

        # API 文档
        location /api/docs {
            proxy_pass http://backend;
        }
        location /api/openapi.json {
            proxy_pass http://backend;
        }
    }
}
```

---

## 3. PostgreSQL 初始化SQL

```sql
-- docker/postgres/init.sql
-- 容器首次启动时自动执行

-- 启用扩展
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 创建Schema
CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS fundamental;
CREATE SCHEMA IF NOT EXISTS ai;
CREATE SCHEMA IF NOT EXISTS strategy;
CREATE SCHEMA IF NOT EXISTS backtest;
CREATE SCHEMA IF NOT EXISTS trade;
CREATE SCHEMA IF NOT EXISTS risk;
CREATE SCHEMA IF NOT EXISTS audit;

-- 设置搜索路径
ALTER DATABASE quant_trader SET search_path TO public, market, fundamental, ai, strategy, backtest, trade, risk, audit;

-- 创建只读用户（供Grafana/监控使用）
CREATE USER quant_readonly WITH PASSWORD 'readonly_password';
GRANT CONNECT ON DATABASE quant_trader TO quant_readonly;
GRANT USAGE ON SCHEMA market, fundamental, ai, strategy, backtest, trade, risk TO quant_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA market TO quant_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA trade TO quant_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA ai TO quant_readonly;

-- 审计Schema只读（连admin也不能DELETE）
REVOKE DELETE, UPDATE, TRUNCATE ON ALL TABLES IN SCHEMA audit FROM PUBLIC;
```

---

## 4. Redis 配置

```conf
# docker/redis/redis.conf

# 安全
requirepass ${REDIS_PASSWORD}
bind 0.0.0.0

# 内存管理
maxmemory 2gb
maxmemory-policy allkeys-lru    # 内存满时淘汰最少使用的key

# 持久化（Celery任务不能丢失）
appendonly yes
appendfsync everysec             # 每秒fsync（性能和安全的平衡）
save 3600 1                      # 1小时内有1次写操作则持久化
save 300 100                     # 5分钟内有100次写操作则持久化

# 网络
timeout 0
tcp-keepalive 300

# 日志
loglevel notice

# 数据库数量
databases 2
# DB 0: 应用缓存（行情/K线等）
# DB 1: Celery Broker & Backend（任务队列）
```

---

## 5. 数据库迁移文件模板

```python
# backend/alembic/versions/001_initial_schema.py
"""Initial schema - all tables

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── fundamental.stocks ──
    op.execute("CREATE SCHEMA IF NOT EXISTS fundamental")
    op.create_table(
        'stocks',
        sa.Column('code', sa.String(10), primary_key=True),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('full_name', sa.String(100)),
        sa.Column('market', sa.String(5), nullable=False),
        sa.Column('board', sa.String(20)),
        sa.Column('sector', sa.String(50)),
        sa.Column('sub_sector', sa.String(50)),
        sa.Column('list_date', sa.Date),
        sa.Column('delist_date', sa.Date),
        sa.Column('total_shares', sa.BigInteger),
        sa.Column('float_shares', sa.BigInteger),
        sa.Column('is_st', sa.Boolean, default=False),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('currency', sa.String(5), default='CNY'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        schema='fundamental'
    )

    # ── market.klines（TimescaleDB超表）──
    op.execute("CREATE SCHEMA IF NOT EXISTS market")
    op.execute("""
        CREATE TABLE market.klines (
            time            TIMESTAMPTZ     NOT NULL,
            stock_code      VARCHAR(10)     NOT NULL,
            period          VARCHAR(10)     NOT NULL,
            open            NUMERIC(12,4)   NOT NULL,
            high            NUMERIC(12,4)   NOT NULL,
            low             NUMERIC(12,4)   NOT NULL,
            close           NUMERIC(12,4)   NOT NULL,
            volume          BIGINT          NOT NULL,
            amount          NUMERIC(20,2)   NOT NULL,
            vwap            NUMERIC(12,4),
            turnover_rate   NUMERIC(8,4),
            adj_factor      NUMERIC(12,6)   DEFAULT 1.0,
            adj_close       NUMERIC(12,4),
            PRIMARY KEY (time, stock_code, period)
        )
    """)
    op.execute("""
        SELECT create_hypertable(
            'market.klines', 'time',
            chunk_time_interval => INTERVAL '1 month',
            if_not_exists => TRUE
        )
    """)
    op.execute("CREATE INDEX idx_klines_stock_period ON market.klines(stock_code, period, time DESC)")

    # ── trade.orders ──
    op.execute("CREATE SCHEMA IF NOT EXISTS trade")
    op.execute("""
        CREATE TABLE trade.orders (
            id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
            idempotency_key     VARCHAR(64)     UNIQUE NOT NULL,
            stock_code          VARCHAR(10)     NOT NULL,
            signal_id           UUID,
            strategy_id         INT,
            side                VARCHAR(5)      NOT NULL CHECK (side IN ('BUY', 'SELL')),
            order_type          VARCHAR(10)     DEFAULT 'LIMIT' CHECK (order_type IN ('MARKET', 'LIMIT')),
            quantity            INT             NOT NULL CHECK (quantity > 0),
            limit_price         NUMERIC(12,4),
            filled_quantity     INT             DEFAULT 0,
            avg_fill_price      NUMERIC(12,4),
            commission          NUMERIC(12,4)   DEFAULT 0,
            status              VARCHAR(20)     DEFAULT 'PENDING'
                                CHECK (status IN ('PENDING','SUBMITTED','PARTIAL','FILLED','CANCELLED','FAILED')),
            mode                VARCHAR(15)     NOT NULL CHECK (mode IN ('simulation', 'paper', 'live')),
            trigger_source      VARCHAR(20)     DEFAULT 'auto',
            operator            VARCHAR(50),
            created_at          TIMESTAMPTZ     DEFAULT NOW(),
            submitted_at        TIMESTAMPTZ,
            filled_at           TIMESTAMPTZ,
            cancelled_at        TIMESTAMPTZ,
            broker_order_id     VARCHAR(100),
            reject_reason       TEXT
        )
    """)
    op.execute("CREATE INDEX idx_orders_stock ON trade.orders(stock_code, created_at DESC)")
    op.execute("CREATE INDEX idx_orders_status ON trade.orders(status)")

    # ── risk.risk_rules（初始化默认规则）──
    op.execute("CREATE SCHEMA IF NOT EXISTS risk")
    op.execute("""
        CREATE TABLE risk.risk_rules (
            id          SERIAL PRIMARY KEY,
            rule_code   VARCHAR(50) UNIQUE NOT NULL,
            rule_name   VARCHAR(100) NOT NULL,
            rule_type   VARCHAR(20) NOT NULL,
            is_hard     BOOLEAN DEFAULT TRUE,
            threshold   NUMERIC(12,4) NOT NULL,
            action      VARCHAR(20) NOT NULL,
            is_enabled  BOOLEAN DEFAULT TRUE,
            description TEXT,
            updated_at  TIMESTAMPTZ DEFAULT NOW(),
            updated_by  VARCHAR(50)
        )
    """)
    op.execute("""
        INSERT INTO risk.risk_rules (rule_code, rule_name, rule_type, is_hard, threshold, action, description)
        VALUES
        ('MAX_SINGLE_POSITION', '单票最大仓位', 'position', TRUE, 0.10, 'block', '单票持仓不超过总资产10%'),
        ('MAX_TOTAL_POSITION', '总仓位上限', 'position', TRUE, 0.80, 'block', '总持仓不超过80%'),
        ('MAX_DAILY_LOSS', '日最大亏损', 'loss', TRUE, 0.03, 'fuse', '日亏损超3%熔断'),
        ('MAX_DRAWDOWN', '最大回撤熔断', 'loss', TRUE, 0.15, 'fuse', '回撤超15%熔断'),
        ('MAX_DAILY_ORDER_COUNT', '日下单上限', 'frequency', TRUE, 20, 'block', '单日下单不超过20次'),
        ('MIN_DAILY_AMOUNT', '最低日成交额', 'liquidity', TRUE, 50000000, 'block', '日成交额低于5000万禁止买入'),
        ('BLOCK_ST', '禁止买入ST', 'special', TRUE, 0, 'block', '禁止买入ST股'),
        ('MAX_SECTOR_CONCENTRATION', '行业集中度', 'concentration', TRUE, 0.40, 'block', '单行业不超过40%')
    """)

    # ── audit.operation_logs ──
    op.execute("CREATE SCHEMA IF NOT EXISTS audit")
    op.execute("""
        CREATE TABLE audit.operation_logs (
            id          BIGSERIAL PRIMARY KEY,
            session_id  VARCHAR(64),
            operator    VARCHAR(50),
            ip_address  INET,
            operation   VARCHAR(100) NOT NULL,
            entity_type VARCHAR(50),
            entity_id   VARCHAR(100),
            before_data JSONB,
            after_data  JSONB,
            result      VARCHAR(20),
            error_detail TEXT,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("REVOKE UPDATE, DELETE ON audit.operation_logs FROM PUBLIC")

    # ── 订单状态变更触发器 ──
    op.execute("""
        CREATE OR REPLACE FUNCTION audit.log_order_change()
        RETURNS TRIGGER AS $$
        BEGIN
            INSERT INTO audit.operation_logs(operation, entity_type, entity_id, before_data, after_data)
            VALUES ('ORDER_STATUS_CHANGE', 'order', NEW.id::text, to_jsonb(OLD), to_jsonb(NEW));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_order_audit
        AFTER UPDATE ON trade.orders
        FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status)
        EXECUTE FUNCTION audit.log_order_change()
    """)


def downgrade() -> None:
    # 生产环境不允许降级
    raise RuntimeError("Downgrade not allowed in production environment")
```

---

## 6. 核心配置类

```python
# backend/app/core/config.py

from pydantic_settings import BaseSettings
from typing import List
import os

class Settings(BaseSettings):
    # 环境
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost"]

    # 数据库
    DATABASE_URL: str
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # Redis
    REDIS_URL: str
    REDIS_PASSWORD: str = ""

    # AI模型
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_TIMEOUT: int = 30

    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20241022"
    ANTHROPIC_TIMEOUT: int = 30

    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    QWEN_API_KEY: str = ""
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/api/v1"
    QWEN_MODEL: str = "qwen-plus"

    # ChromaDB
    CHROMA_PERSIST_DIR: str = "/app/vector_db"

    # 交易配置
    TRADE_MODE: str = "simulation"   # simulation / paper / live

    # 信号阈值
    SIGNAL_MIN_CONFIDENCE: float = 0.65
    SIGNAL_BUY_THRESHOLD: float = 0.68
    SIGNAL_SELL_THRESHOLD: float = 0.32
    SIGNAL_VALIDITY_HOURS: int = 24

    # 数据同步
    DATA_SYNC_INTERVAL_REALTIME: int = 3
    DATA_CACHE_TTL_QUOTE: int = 5
    DATA_CACHE_TTL_KLINE: int = 300

    # 通知
    DINGTALK_WEBHOOK: str = ""
    ENABLE_DINGTALK_NOTIFY: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = True

    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    def validate_ai_keys(self) -> dict:
        """检查哪些AI服务可用"""
        return {
            'openai': bool(self.OPENAI_API_KEY),
            'anthropic': bool(self.ANTHROPIC_API_KEY),
            'deepseek': bool(self.DEEPSEEK_API_KEY),
            'qwen': bool(self.QWEN_API_KEY),
        }

settings = Settings()


# backend/app/db.py

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from contextlib import asynccontextmanager
from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,              # 连接前检查连接是否有效
    pool_recycle=3600,               # 1小时回收连接
    echo=settings.APP_ENV == "development",
)

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

@asynccontextmanager
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# FastAPI依赖注入
async def get_db_dep():
    async with get_db() as db:
        yield db
```

---

## 7. 结构化日志配置

```python
# backend/app/core/logging.py

import structlog
import logging
import sys
from app.core.config import settings

def setup_logging():
    """配置结构化日志（JSON格式，便于ELK/Grafana Loki收集）"""
    level = getattr(logging, settings.LOG_LEVEL.upper())

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer() if settings.is_production()
            else structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

logger = structlog.get_logger()

# 使用示例
# logger.info("order_created", order_id=order_id, stock_code=code, side=side)
# logger.error("ai_agent_failed", agent="trend", error=str(e), latency_ms=latency)
```

---

## 8. 健康检查脚本

```python
# backend/scripts/health_check.py
"""
系统健康检查脚本
在部署后和日常运维中使用
"""

import asyncio
import sys

async def check_database():
    from app.db import engine
    from sqlalchemy import text
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT version()"))
        version = result.scalar()
        print(f"✅ PostgreSQL: {version[:50]}")

async def check_redis():
    import redis.asyncio as aioredis
    import os
    r = aioredis.from_url(os.getenv('REDIS_URL'))
    pong = await r.ping()
    print(f"✅ Redis: {'PONG' if pong else 'FAILED'}")
    await r.aclose()

async def check_timescaledb():
    from app.db import engine
    from sqlalchemy import text
    async with engine.begin() as conn:
        result = await conn.execute(text(
            "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'"
        ))
        version = result.scalar()
        print(f"✅ TimescaleDB: {version}")

async def check_ai_keys():
    from app.core.config import settings
    available = settings.validate_ai_keys()
    for service, is_available in available.items():
        status = "✅" if is_available else "❌"
        print(f"{status} AI Key: {service} {'配置' if is_available else '未配置'}")

async def check_chromadb():
    import chromadb
    import os
    client = chromadb.PersistentClient(path=os.getenv('CHROMA_PERSIST_DIR', '/app/vector_db'))
    collections = client.list_collections()
    print(f"✅ ChromaDB: {len(collections)} collections")

async def main():
    print("=== AI Quant Trader Pro 系统健康检查 ===\n")
    checks = [
        ("数据库", check_database),
        ("Redis", check_redis),
        ("TimescaleDB", check_timescaledb),
        ("AI Keys", check_ai_keys),
        ("ChromaDB", check_chromadb),
    ]

    failed = []
    for name, check_fn in checks:
        try:
            await check_fn()
        except Exception as e:
            print(f"❌ {name}: {e}")
            failed.append(name)

    print(f"\n{'='*40}")
    if failed:
        print(f"❌ {len(failed)} 项检查失败: {', '.join(failed)}")
        sys.exit(1)
    else:
        print("✅ 所有检查通过，系统就绪")

if __name__ == '__main__':
    asyncio.run(main())
```
