-- docker/postgres/init.sql
-- 容器首次启动时自动执行

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS fundamental;
CREATE SCHEMA IF NOT EXISTS ai;
CREATE SCHEMA IF NOT EXISTS strategy;
CREATE SCHEMA IF NOT EXISTS backtest;
CREATE SCHEMA IF NOT EXISTS trade;
CREATE SCHEMA IF NOT EXISTS risk;
CREATE SCHEMA IF NOT EXISTS audit;

ALTER DATABASE quant_trader SET search_path TO public, market, fundamental, ai, strategy, backtest, trade, risk, audit;

-- 生产请通过环境变量/密钥管理覆盖该只读账号密码
CREATE USER quant_readonly WITH PASSWORD 'CHANGE_ME_READONLY_PASSWORD';
GRANT CONNECT ON DATABASE quant_trader TO quant_readonly;
GRANT USAGE ON SCHEMA market, fundamental, ai, strategy, backtest, trade, risk TO quant_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA market TO quant_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA trade TO quant_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA ai TO quant_readonly;

REVOKE DELETE, UPDATE, TRUNCATE ON ALL TABLES IN SCHEMA audit FROM PUBLIC;