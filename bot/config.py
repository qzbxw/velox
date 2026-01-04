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
    PROXIMITY_THRESHOLD: float = Field(0.005, description="0.5% proximity threshold")
    ALERT_COOLDOWN: int = Field(1800, description="Alert cooldown in seconds (30 mins)")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
