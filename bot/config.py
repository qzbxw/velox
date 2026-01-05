from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    BOT_TOKEN: str = Field(..., description="Telegram Bot Token")
    MONGO_URI: str = Field("mongodb://mongo:27017", description="MongoDB Connection URI")
    MONGO_DB_NAME: str = Field("hyperliquid_bot", description="Database Name")
    
    # Hyperliquid Config
    HYPERLIQUID_WS_URL: str = Field("wss://api.hyperliquid.xyz/ws", description="Hyperliquid Mainnet WS")
    HYPERLIQUID_API_URL: str = Field("https://api.hyperliquid.xyz", description="Hyperliquid Mainnet REST API")
    
    # App Config
    PROXIMITY_THRESHOLD: float = Field(0.005, description="Legacy proximity threshold (fraction, 0.005=0.5%)")
    BUY_PROXIMITY_THRESHOLD: float = Field(0.003, description="Buy proximity threshold (fraction, 0.003=0.3%)")
    SELL_PROXIMITY_THRESHOLD: float = Field(0.007, description="Sell proximity threshold (fraction, 0.007=0.7%)")
    PROXIMITY_USD_THRESHOLD: float = Field(5.0, description="Also alert when USD distance to limit is below this value")
    ALERT_COOLDOWN: int = Field(1800, description="Alert cooldown in seconds (30 mins)")

    MARKET_HISTORY_MINUTES: int = Field(15, description="How many minutes of mid price history to keep in memory")
    WATCH_ALERT_PCT: float = Field(0.02, description="Watchlist alert percent move threshold (fraction, 0.02=2%)")
    WATCH_ALERT_WINDOW_SEC: int = Field(300, description="Watchlist alert time window in seconds")
    WATCH_ALERT_COOLDOWN: int = Field(900, description="Watchlist alert cooldown per symbol in seconds")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
