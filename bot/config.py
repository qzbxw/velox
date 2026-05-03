from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    BOT_TOKEN: str = Field(..., description="Telegram Bot Token")
    MONGO_URI: str = Field("mongodb://mongo:27017", description="MongoDB Connection URI")
    MONGO_DB_NAME: str = Field("hyperliquid_bot", description="Database Name")
    
    # Hyperliquid Config
    HYPERLIQUID_WS_URL: str = Field("wss://api.hyperliquid.xyz/ws", description="Hyperliquid Mainnet WS")
    HYPERLIQUID_API_URL: str = Field("https://api.hyperliquid.xyz", description="Hyperliquid Mainnet REST API")

    # External APIs
    GEMINI_API_KEY: str = Field("", description="Google Gemini API Key")
    MARKET_OVERVIEW_ENABLE_SEARCH_NEWS: bool = Field(False, description="Enable Gemini Google Search enrichment for news digests")

    # RSS Engine
    RSS_REFRESH_INTERVAL_MIN: int = Field(15, description="RSS cache refresh interval in minutes")
    RSS_ARTICLE_TTL_HOURS: int = Field(24, description="How long to keep articles in cache (hours)")
    RSS_FETCH_TIMEOUT: int = Field(12, description="Timeout per single RSS feed fetch (seconds)")

    # News Summarizer (AI subagent)
    NEWS_SUMMARIZER_ENABLED: bool = Field(True, description="Enable AI pre-summarization of RSS headlines")
    NEWS_SUMMARIZER_MODEL: str = Field("gemma-4-31b-it", description="Gemini model for news summarization")

    # Agentic Market Intelligence
    AGENT_ENABLED: bool = Field(True, description="Enable agentic market overview pipeline")
    AGENT_SEARCH_ENABLED: bool = Field(True, description="Enable agent search collectors")
    AGENT_BRAVE_SEARCH_ENABLED: bool = Field(True, description="Enable Brave Search scraping collector")
    AGENT_DUCKDUCKGO_FALLBACK_ENABLED: bool = Field(True, description="Enable DuckDuckGo search fallback collector")
    AGENT_MAX_SOURCES_PER_RUN: int = Field(80, description="Maximum scored sources kept per agent run")
    AGENT_MAX_SEARCH_QUERIES: int = Field(12, description="Maximum search queries per agent run")
    AGENT_SOURCE_CACHE_TTL_MIN: int = Field(60, description="Agent source cache TTL in minutes")
    AGENT_EVENT_TTL_HOURS: int = Field(48, description="Agent market event freshness TTL in hours")
    AGENT_LLM_MODEL: str = Field("gemma-4-31b-it", description="Gemini model for final agent report synthesis")
    AGENT_EVENT_EXTRACTOR_MODEL: str = Field("gemini-3.1-flash-lite-preview", description="Gemini model for event extraction")
    AGENT_PIPELINE_TIMEOUT_SEC: int = Field(120, description="Total agent pipeline timeout in seconds")
    AGENT_TOOL_TIMEOUT_SEC: int = Field(15, description="Per agent tool timeout in seconds")

    FARSIDE_BTC_URL: str = Field("https://farside.co.uk/btc/", description="Farside BTC ETF Flow URL")
    FARSIDE_ETH_URL: str = Field("https://farside.co.uk/eth/", description="Farside ETH ETF Flow URL")
    PAY_SUPPORT_CONTACT: str = Field("", description="Telegram handle or URL for payment support")
    
    # App Config
    PROXIMITY_THRESHOLD: float = Field(0.01, description="Legacy proximity threshold (fraction, 0.01=1%)")
    BUY_PROXIMITY_THRESHOLD: float = Field(0.01, description="Buy proximity threshold (fraction, 0.01=1%)")
    SELL_PROXIMITY_THRESHOLD: float = Field(0.015, description="Sell proximity threshold (fraction, 0.015=1.5%)")
    PROXIMITY_USD_THRESHOLD: float = Field(10.0, description="Also alert when USD distance to limit is below this value")
    ALERT_COOLDOWN: int = Field(600, description="Alert cooldown in seconds (10 mins)")

    MARKET_HISTORY_MINUTES: int = Field(15, description="How many minutes of mid price history to keep in memory")
    WATCH_ALERT_PCT: float = Field(0.02, description="Watchlist alert percent move threshold (fraction, 0.02=2%)")
    WATCH_ALERT_WINDOW_SEC: int = Field(300, description="Watchlist alert time window in seconds")
    WATCH_ALERT_COOLDOWN: int = Field(900, description="Watchlist alert cooldown per symbol in seconds")
    
    # Renderer
    RENDER_CONCURRENCY: int = Field(5, description="Maximum number of concurrent Chromium renders allowed")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

HLP_VAULT_ADDR = "0xdf13098394e1832014b0df3f91285497"

DIGEST_TARGETS = [
    "portfolio_daily",
    "portfolio_weekly",
    "hlp_daily",
    "vault_weekly",
    "vault_monthly",
]
