import aiohttp
import logging
from bot.config import settings

logger = logging.getLogger(__name__)

async def get_user_state(wallet_address: str):
    """Fetch user state (balances) via REST API."""
    url = f"{settings.HYPERLIQUID_API_URL}/info"
    # Use spotClearinghouseState for Spot balances
    payload = {
        "type": "spotClearinghouseState",
        "user": wallet_address
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                logger.error(f"Error fetching state: {resp.status}")
                return None

async def get_spot_meta():
    """Fetch spot metadata (universe)."""
    url = f"{settings.HYPERLIQUID_API_URL}/info"
    payload = {"type": "spotMeta"}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                return await resp.json()
            return None
