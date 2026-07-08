from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost"]

    DATABASE_URL: str
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

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

    SIGNAL_MIN_CONFIDENCE: float = 0.65
    SIGNAL_BUY_THRESHOLD: float = 0.68
    SIGNAL_SELL_THRESHOLD: float = 0.32
    SIGNAL_VALIDITY_HOURS: int = 24

    DATA_SYNC_INTERVAL_REALTIME: int = 3
    DATA_CACHE_TTL_QUOTE: int = 5
    DATA_CACHE_TTL_KLINE: int = 300

    DINGTALK_WEBHOOK: str = ""
    ENABLE_DINGTALK_NOTIFY: bool = False

    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    def validate_ai_keys(self) -> dict[str, bool]:
        return {
            "openai": bool(self.OPENAI_API_KEY),
            "anthropic": bool(self.ANTHROPIC_API_KEY),
            "deepseek": bool(self.DEEPSEEK_API_KEY),
            "qwen": bool(self.QWEN_API_KEY),
        }


settings = Settings()