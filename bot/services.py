import aiohttp
import logging
import asyncio
import time
from bot.config import settings

logger = logging.getLogger(__name__)

# Cache for symbol mappings (ID -> Name)
_SYMBOL_CACHE = {
    "map": {},  # id (int/str) -> name (str)
    "last_update": 0
}

async def ensure_symbol_mapping():
    """Ensures the symbol mapping cache is populated and up-to-date."""
    now = time.time()
    if now - _SYMBOL_CACHE["last_update"] < 300 and _SYMBOL_CACHE["map"]:
        return

    # Fetch both Spot and Perps meta
    spot_meta, perps_meta = await asyncio.gather(
        get_spot_meta(),
        get_perps_meta(),
        return_exceptions=True
    )

    new_map = {}

    # Process Spot Meta
    if isinstance(spot_meta, dict):
        # Universe mapping (Index -> Name)
        universe = spot_meta.get("universe", [])
        for idx, token in enumerate(universe):
            if isinstance(token, dict) and "name" in token:
                 new_map[str(token.get("index", idx))] = token["name"]
                 new_map[f"@{idx}"] = token["name"] # Handle potential @ID format
            elif isinstance(token, str): # Sometimes universe is just strings? (Rare in HL spot)
                 new_map[str(idx)] = token

        # Token ID mapping
        tokens = spot_meta.get("tokens", [])
        for t in tokens:
            if isinstance(t, dict):
                tid = t.get("tokenId")
                name = t.get("name")
                if tid is not None and name:
                    # Do not overwrite existing keys (Universe index priority for Spot)
                    s_tid = str(tid)
                    if s_tid not in new_map:
                        new_map[s_tid] = name
                    
                    at_tid = f"@{tid}"
                    if at_tid not in new_map:
                        new_map[at_tid] = name

    # Process Perps Meta
    if isinstance(perps_meta, dict):
        universe = perps_meta.get("universe", [])
        for idx, asset in enumerate(universe):
            name = asset.get("name")
            if name:
                # Perps often reference by index in the universe array
                new_map[str(idx)] = name
                new_map[f"@{idx}"] = name 
                # Also map the name to itself for safety
                new_map[name] = name

    _SYMBOL_CACHE["map"] = new_map
    _SYMBOL_CACHE["last_update"] = now
    logger.info(f"Refreshed symbol mapping. Total keys: {len(new_map)}")

async def get_symbol_name(token_id: str | int) -> str:
    """Resolves a token ID (or index) to its symbol name."""
    await ensure_symbol_mapping()
    
    s_id = str(token_id)
    
    # Hardcoded overrides for canonical Perps
    if s_id == "0": return "BTC"
    if s_id == "1": return "ETH"
    
    # Common symbols bypass (Safety)
    if s_id in ("BTC", "ETH", "SOL", "HYPE", "USDC"):
        return s_id
    
    # If the input is already a known symbol name (e.g. "BTC", "ETH"), return it directly
    # This prevents weird double lookups or failures if the ID is actually a name
    if s_id in _SYMBOL_CACHE["map"].values():
        return s_id

    # Check exact match
    if s_id in _SYMBOL_CACHE["map"]:
        return _SYMBOL_CACHE["map"][s_id]
    
    # Check @ID format
    if not s_id.startswith("@"):
        at_id = f"@{s_id}"
        if at_id in _SYMBOL_CACHE["map"]:
            return _SYMBOL_CACHE["map"][at_id]
            
    # Fallback: if it looks like a standard name (not an ID), return it
    if not s_id.isdigit() and not s_id.startswith("@"):
        return s_id
        
    return f"@{s_id}"

def normalize_spot_coin(coin: str | None) -> str:
    if not coin:
        return ""
    c = str(coin).upper()
    if c == "USDC":
        return c
    # If it starts with U and followed by letters (e.g. UPURR), it might be internal name
    # But often spot coins are just "PURR" or "@123"
    if c.startswith("U") and len(c) > 1 and not c[1].isdigit():
         return c[1:]
    return c

def pretty_float(x: float, max_decimals: int = 6) -> str:
    """Human-friendly float: trim trailing zeros while keeping up to max_decimals."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "0"

    # stable formatting then strip
    s = f"{v:.{max_decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s

def extract_avg_entry_from_balance(balance: dict) -> float:
    """Best-effort: try to use avg/entry provided by clearinghouse state.
    Works for both Spot balances and Perps positions.
    """
    if not isinstance(balance, dict):
        return 0.0

    # Perps fields: 'entryPx'
    if "entryPx" in balance:
        try:
            return float(balance["entryPx"])
        except (ValueError, TypeError):
            pass

    # Spot fields
    for k in ("avgPx", "avg_px", "avgPrice", "avgEntry"):
        v = balance.get(k)
        if v is not None:
            try:
                px = float(v)
                if px > 0:
                    return px
            except (TypeError, ValueError):
                pass

    return 0.0

async def get_user_state(wallet_address: str):
    """Fetch Spot user state (balances) via REST API."""
    url = f"{settings.HYPERLIQUID_API_URL}/info"
    payload = {
        "type": "spotClearinghouseState",
        "user": wallet_address
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                logger.error(f"Error fetching spot state: {resp.status}")
                return None

async def get_perps_state(wallet_address: str):
    """Fetch Perps (Futures) user state via REST API."""
    url = f"{settings.HYPERLIQUID_API_URL}/info"
    payload = {
        "type": "clearinghouseState",
        "user": wallet_address
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                logger.error(f"Error fetching perps state: {resp.status}")
                return None

async def get_spot_balances(wallet_address: str) -> list[dict]:
    state = await get_user_state(wallet_address)
    if not isinstance(state, dict):
        return []
    balances = state.get("balances")
    if isinstance(balances, list):
        return balances
    return []

async def get_spot_meta():
    """Fetch spot metadata (universe)."""
    url = f"{settings.HYPERLIQUID_API_URL}/info"
    payload = {"type": "spotMeta"}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                return await resp.json()
            return None

async def get_perps_meta():
    """Fetch perps metadata (universe)."""
    url = f"{settings.HYPERLIQUID_API_URL}/info"
    payload = {"type": "meta"}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                return await resp.json()
            return None

async def get_perps_context():
    """Fetch perps market context (funding, oi, volume, etc)."""
    url = f"{settings.HYPERLIQUID_API_URL}/info"
    payload = {"type": "metaAndAssetCtxs"}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                return await resp.json()
            return None

async def get_open_orders(wallet_address: str):
    url = f"{settings.HYPERLIQUID_API_URL}/info"
    payload = {
        "type": "openOrders",
        "user": wallet_address,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                if isinstance(data, dict) and isinstance(data.get("orders"), list):
                    return data
                if isinstance(data, list):
                    return {"user": wallet_address, "orders": data}
                return data
            logger.error(f"Error fetching openOrders: {resp.status}")
            return None

async def get_all_mids():
    url = f"{settings.HYPERLIQUID_API_URL}/info"
    payload = {"type": "allMids"}

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                if isinstance(data, dict):
                    mids = data.get("mids")
                    if isinstance(mids, dict):
                        return mids
                return None
            logger.error(f"Error fetching allMids: {resp.status}")
            return None

async def get_mid_price(symbol: str) -> float:
    if not symbol:
        return 0.0
    sym = symbol.upper()
    if sym == "USDC":
        return 1.0

    mids = await get_all_mids()
    if not mids:
        return 0.0

    # Try direct match
    if sym in mids:
        try:
            return float(mids[sym])
        except:
            pass
            
    # Try handling generic names if internal name differs
    # (Simplified: logic usually requires mapping back to universe)
    
    return 0.0

async def get_user_portfolio(wallet_address: str):
    """Fetch historical PnL/Portfolio stats (Official API data)."""
    url = f"{settings.HYPERLIQUID_API_URL}/info"
    payload = {
        "type": "portfolio",
        "user": wallet_address
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # logger.info(f"Portfolio response for {wallet_address}: {str(data)[:200]}...")
                    return data
                logger.error(f"Error fetching portfolio for {wallet_address}: Status {resp.status}")
                return None
    except Exception as e:
        logger.error(f"Exception fetching portfolio for {wallet_address}: {e}")
        return None

async def get_user_fills(wallet_address: str):
    """Fetch user trade history (fills)."""
    url = f"{settings.HYPERLIQUID_API_URL}/info"
    payload = {
        "type": "userFills",
        "user": wallet_address
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                return await resp.json()
            logger.error(f"Error fetching fills: {resp.status}")
            return []
