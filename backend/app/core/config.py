from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",  # 忽略 .env 中 compose 专用键（DB_HOST 等）
    )

    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost"]

    DATABASE_URL: str
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    SQL_ECHO: bool = False  # True 时打印全部 SQL（全市场同步时极慢，勿开）

    REDIS_URL: str
    REDIS_PASSWORD: str = ""

    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_TIMEOUT: int = 30

    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20241022"
    ANTHROPIC_TIMEOUT: int = 30

    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_TIMEOUT: int = 30

    QWEN_API_KEY: str = ""
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/api/v1"
    QWEN_MODEL: str = "qwen-plus"
    QWEN_TIMEOUT: int = 30

    A_STOCK_DATA_URL: str = "http://a-stock-data:8080"

    CHROMA_PERSIST_DIR: str = "/app/vector_db"
    CHROMA_COLLECTION_REPORTS: str = "research_reports"
    CHROMA_COLLECTION_ANNOUNCEMENTS: str = "announcements"
    CHROMA_COLLECTION_NEWS: str = "news"

    TRADE_MODE: str = "simulation"

    # Execution safety defaults: no environment may submit an order implicitly.
    TRADING_EXECUTION_ENABLED: bool = False
    AI_ORDER_ENABLED: bool = False
    LIVE_TRADING_ENABLED: bool = False
    PAPER_TRADING_ENABLED: bool = True
    REQUIRE_HUMAN_APPROVAL: bool = True
    ALLOW_SCHEDULED_ORDER: bool = False
    CERTIFIED_BACKTEST_EXECUTION_ENABLED: bool = False
    CERTIFIED_SCREENER_OUTPUT_ENABLED: bool = False

    # 模拟盘：非交易时段是否允许按最近真实行情成交（学习默认 true；严格模式可设 false）
    SIM_ALLOW_OFF_HOURS: bool = True

    # 回测无 K 线时：拉取远程失败后是否用合成数据兜底（开发默认开）
    BACKTEST_ALLOW_SYNTHETIC_KLINE: bool = False
    SYNTHETIC_KLINE_SMOKE_TEST: bool = False
    # 回测前自动回填缺失 K 线
    BACKTEST_AUTO_BACKFILL: bool = True
    # live 无 QMT 时是否允许 Mock 降级（开发 true；生产务必 false）
    # 实盘二次确认令牌：mode=live 时请求体必须带 live_confirm=该值
    LIVE_CONFIRM_TOKEN: str = ""
    # 单笔实盘最大金额（元），0 表示不限制
    LIVE_MAX_ORDER_VALUE: float = 50_000
    # 成交后自动跑券商对账
    AUTO_RECONCILE_ON_FILL: bool = True

    # 可选 API 鉴权：为空则不校验（开发默认）；生产建议设置强随机值
    API_KEY: str = ""

    # 风控阈值（可被环境变量覆盖；DB risk_rules 仅作展示时可同步）
    MAX_SINGLE_POSITION_RATIO: float = 0.10
    WARN_SINGLE_POSITION_RATIO: float = 0.08
    MAX_TOTAL_POSITION_RATIO: float = 0.80
    MAX_DAILY_LOSS_RATIO: float = 0.03
    MAX_DRAWDOWN_RATIO: float = 0.15
    MAX_DAILY_ORDER_COUNT: int = 20
    MAX_SECTOR_CONCENTRATION_RATIO: float = 0.40
    MIN_DAILY_AMOUNT: float = 50_000_000

    SIGNAL_MIN_CONFIDENCE: float = 0.65
    SIGNAL_BUY_THRESHOLD: float = 0.68
    SIGNAL_SELL_THRESHOLD: float = 0.32
    SIGNAL_VALIDITY_HOURS: int = 24

    DATA_SYNC_INTERVAL_REALTIME: int = 3
    # 行情缓存秒数：UI 刷新友好，过短会导致每次打外部源
    DATA_CACHE_TTL_QUOTE: int = 15
    DATA_CACHE_TTL_KLINE: int = 300

    DINGTALK_WEBHOOK: str = ""
    ENABLE_DINGTALK_NOTIFY: bool = False
    # 哪些级别推送钉钉，逗号分隔：CRITICAL,ERROR,WARNING,INFO
    DINGTALK_ALERT_LEVELS: str = "CRITICAL,ERROR"
    DINGTALK_COOLDOWN_SECONDS: int = 300
    # 钉钉静默时段（Asia/Shanghai）：HH:MM-HH:MM，可跨日如 23:00-08:00；空=不静默
    DINGTALK_QUIET_HOURS: str = ""
    # 静默时段仍推送的级别
    DINGTALK_QUIET_BYPASS_LEVELS: str = "CRITICAL"

    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    def dingtalk_levels(self) -> set[str]:
        raw = self.DINGTALK_ALERT_LEVELS or "CRITICAL,ERROR"
        return {p.strip().upper() for p in raw.split(",") if p.strip()}

    def dingtalk_quiet_bypass_levels(self) -> set[str]:
        raw = self.DINGTALK_QUIET_BYPASS_LEVELS or "CRITICAL"
        return {p.strip().upper() for p in raw.split(",") if p.strip()}

    def validate_ai_keys(self) -> dict[str, bool]:
        return {
            "openai": bool(self.OPENAI_API_KEY),
            "anthropic": bool(self.ANTHROPIC_API_KEY),
            "deepseek": bool(self.DEEPSEEK_API_KEY),
            "qwen": bool(self.QWEN_API_KEY),
        }


settings = Settings()
