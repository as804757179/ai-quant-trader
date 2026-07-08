# 01 — 项目总览与设计哲学

---

## 1. 项目定位

**AI Quant Trader Pro** 是一个本地优先（Local-first）、企业级架构、AI驱动的A股量化交易系统。

**不是：**
- 学习项目 / Demo
- 纯回测框架
- 信号订阅服务

**是：**
- 可运行在本地服务器的完整交易平台
- 支持从回测→纸盘→实盘的完整生命周期
- AI多Agent协同决策 + 严格风控保障

---

## 2. 系统三层核心

```
┌─────────────────────────────────────────────────────┐
│  Layer 1: 数据层                                     │
│  a-stock-data → DataService → TimescaleDB + Redis    │
│  职责：唯一数据源、数据质量保证、时序数据存储          │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│  Layer 2: AI决策层                                   │
│  AI-Trader → Multi-Agent → RAG + MCP → Signal        │
│  职责：多模型协同分析、信号生成、置信度评估            │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│  Layer 3: 交易执行层                                 │
│  RiskEngine → OrderManager → QMT/Simulation          │
│  职责：风控检查、订单管理、实盘/模拟执行              │
└─────────────────────────────────────────────────────┘
```

---

## 3. 技术选型决策

### 3.1 为什么选 FastAPI 而非 Django？

| 维度 | FastAPI | Django |
|------|---------|--------|
| 异步支持 | 原生async | 有限 |
| WebSocket | 原生支持 | 需插件 |
| 性能 | 高（行情推送场景关键） | 中 |
| 类型安全 | Pydantic V2 | 弱 |
| 适合场景 | 实时数据API | 后台管理 |

### 3.2 为什么选 PostgreSQL + TimescaleDB？

- TimescaleDB 是 PostgreSQL 扩展，专为时序数据优化
- K线数据（亿级行）查询性能比普通 PostgreSQL 快 10-100x
- 支持时间分区、连续聚合（自动生成日/周/月K线）
- 与 SQLAlchemy 完全兼容，无额外学习成本

### 3.3 为什么选 ChromaDB 做向量库？

- 本地部署，无需外部服务
- Python原生，与FastAPI集成简单
- 适合研报/公告文档量级（百万级向量）
- 支持持久化存储

### 3.4 为什么 AI Agent 用多模型而非单一模型？

- 不同模型有不同能力偏好：GPT擅长推理，Claude擅长长文档分析，Qwen擅长中文情绪
- 多模型投票降低单一模型幻觉风险
- 任一模型API故障时系统仍可运行（降级为剩余模型）
- 成本可控：短线信号用便宜模型，基本面分析用高质量模型

---

## 4. 两个核心外部项目

### 4.1 a-stock-data（数据引擎）

**GitHub：** https://github.com/simonlin1212/a-stock-data

**集成方式：** Git Submodule，封装为内部 DataService

**提供数据：**
- 实时行情（Level 1）
- K线（1min / 5min / 15min / 30min / 60min / 日 / 周）
- 财务报表（季报/年报）
- 资金流向（主力/超大单/大单/中单/散户）
- 龙虎榜
- 北向资金（沪深港通）
- 新闻 / 公告 / 研报
- 股东数据

**数据质量策略：**
- 每次拉取后做数值合理性校验（价格>0，成交量>0，OHLC逻辑关系）
- 数据入库时记录来源和拉取时间戳
- 异常数据告警但不阻断系统（使用上一个有效值）

### 4.2 AI-Trader（AI决策框架）

**GitHub：** https://github.com/HKUDS/AI-Trader

**集成方式：** Git Submodule，改造其Agent框架适配本系统

**使用部分：**
- 多Agent协作框架
- Agent辩论/讨论机制
- 交易信号格式标准

**改造部分：**
- 替换数据源为 a-stock-data
- 增加 RAG 检索增强
- 增加 MCP 工具调用
- 增加信号置信度校准
- 增加完整的 Prompt 模板

---

## 5. 系统运行模式

```
模式1: 纯研究模式
  → 只做数据分析和回测，不产生真实信号
  → 用于策略研发阶段

模式2: 纸盘模式（Paper Trading）
  → 产生信号，模拟执行，不操作真实资金
  → 用于验证策略实盘可行性（最少跑3个月）

模式3: 半自动实盘
  → AI产生信号，人工确认后执行
  → 适合初期实盘阶段

模式4: 全自动实盘
  → AI信号经风控检查后自动执行
  → 必须在半自动模式验证6个月以上才可开启
```

**模式切换需要在管理后台手动操作，不能通过API动态切换，防止意外触发。**

---

## 6. 项目目录结构（顶层）

```
AI-Quant-Trader-Pro/
│
├── backend/                    # FastAPI 后端服务
│   ├── app/
│   │   ├── api/               # 路由层
│   │   ├── core/              # 核心配置
│   │   ├── db/                # 数据库连接、迁移
│   │   ├── models/            # ORM模型
│   │   ├── schemas/           # Pydantic schemas
│   │   ├── services/          # 业务逻辑
│   │   ├── ai/                # AI决策层
│   │   ├── strategy/          # 策略引擎
│   │   ├── backtest/          # 回测引擎
│   │   ├── risk/              # 风控引擎
│   │   ├── trade/             # 交易执行
│   │   ├── data/              # 数据层
│   │   ├── screener/          # 选股系统
│   │   ├── rag/               # RAG系统
│   │   └── ws/                # WebSocket
│   ├── tests/                 # 后端测试
│   ├── alembic/               # 数据库迁移
│   ├── scripts/               # 运维脚本
│   ├── Dockerfile
│   └── requirements.txt
│
├── worker/                    # Celery 任务调度服务
│   ├── tasks/
│   │   ├── market.py          # 行情同步任务
│   │   ├── ai.py              # AI分析任务
│   │   ├── screening.py       # 选股任务
│   │   └── maintenance.py     # 维护任务
│   ├── celery_app.py
│   └── Dockerfile
│
├── frontend/                  # React 前端
│   ├── src/
│   │   ├── pages/             # 8个页面
│   │   ├── components/        # 公共组件
│   │   ├── hooks/             # 自定义hooks
│   │   ├── store/             # Zustand状态
│   │   ├── api/               # API客户端
│   │   └── ws/                # WebSocket客户端
│   └── Dockerfile
│
├── vector_db/                 # ChromaDB 持久化目录
├── docker/                    # nginx等配置
├── a-stock-data/              # 数据子模块（git submodule）
├── AI-Trader/                 # AI框架子模块（git submodule）
├── docs/                      # 本文档包所在目录
├── scripts/                   # 全局脚本
├── .env.example
├── docker-compose.yml
├── docker-compose.dev.yml     # 开发环境配置
└── Makefile                   # 常用命令快捷键
```

---

## 7. Makefile 快捷命令

```makefile
# Makefile

.PHONY: up down dev test migrate seed

# 启动生产环境
up:
	docker compose up -d

# 停止所有服务
down:
	docker compose down

# 开发模式（含热重载）
dev:
	docker compose -f docker-compose.dev.yml up

# 初始化数据库
migrate:
	docker compose exec api alembic upgrade head

# 导入初始数据（股票列表）
seed:
	docker compose exec api python scripts/seed_stocks.py

# 回填历史K线（首次部署）
backfill:
	docker compose exec worker python scripts/backfill_kline.py --years=3

# 运行测试
test:
	docker compose exec api pytest tests/ -v --cov=app

# 查看日志
logs:
	docker compose logs -f api worker

# 进入后端容器
shell:
	docker compose exec api bash
```

---

## 8. 版本迭代计划

| 版本 | 里程碑 | 核心功能 |
|------|--------|---------|
| v0.1 | MVP | Docker启动、数据接入、基础API、前端框架 |
| v0.2 | AI核心 | 4个Agent、信号生成、AI分析页 |
| v0.3 | 自动化 | Celery调度、WebSocket推送、选股系统 |
| v0.4 | 回测 | 回测引擎、Walk-Forward、AutoML优化 |
| v0.5 | 风控完善 | 完整风控、VaR、压力测试、审计日志 |
| v0.6 | RAG+MCP | 研报向量化、MCP工具接入 |
| v1.0 | 纸盘上线 | 完整纸盘、对账、监控告警 |
| v2.0 | 实盘 | QMT接入、实盘风控加固、DR方案 |
