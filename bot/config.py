from pydantic_settings import BaseSettings
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
    FARSIDE_BTC_URL: str = Field("https://farside.co.uk/btc/", description="Farside BTC ETF Flow URL")
    FARSIDE_ETH_URL: str = Field("https://farside.co.uk/eth/", description="Farside ETH ETF Flow URL")
    
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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
