import aiohttp
import logging
import asyncio
import time
from bot.config import settings

logger = logging.getLogger(__name__)

# --- Rate Limiter ---
async def _rate_limit():
    # Simple delay to stay under ~1200 req/min (20/s)
    # 0.06s * 1 = 0.06s delay per call.
    await asyncio.sleep(0.06)

# Cache for symbol mappings (ID -> Name)
_SYMBOL_CACHE = {
    "spot": {},  # id (int/str) -> name (str)
    "perp": {},  # id (int/str) -> name (str)
    "last_update": 0
}

async def ensure_symbol_mapping():
    """Ensures the symbol mapping cache is populated and up-to-date."""
    now = time.time()
    if now - _SYMBOL_CACHE["last_update"] < 300 and _SYMBOL_CACHE["spot"]:
        return

    # Fetch both Spot and Perps meta
    spot_meta, perps_meta = await asyncio.gather(
        get_spot_meta(),
        get_perps_meta(),
        return_exceptions=True
    )

    new_spot = {}
    new_perp = {}

    # Process Spot Meta
    if isinstance(spot_meta, dict):
        # 1. Map tokens by their index first
        tokens_map = {} # token_idx -> name
        tokens_list = spot_meta.get("tokens", [])
        for t in tokens_list:
            if isinstance(t, dict):
                t_idx = t.get("index")
                t_name = t.get("name")
                if t_idx is not None and t_name:
                    tokens_map[t_idx] = t_name
                    # Also map tokenId for direct lookups
                    tid = t.get("tokenId")
                    if tid:
                        new_spot[str(tid)] = t_name

        # 2. Process Universe (Markets)
        universe = spot_meta.get("universe", [])
        for idx, market in enumerate(universe):
            if isinstance(market, dict):
                m_name = market.get("name")
                m_idx = market.get("index", idx)
                
                # If name is like @1, try to resolve from tokens
                if m_name and m_name.startswith("@") and "tokens" in market:
                    m_tokens = market["tokens"]
                    if len(m_tokens) >= 2:
                        base_idx = m_tokens[0]
                        base_name = tokens_map.get(base_idx)
                        if base_name:
                            m_name = f"{base_name}/USDC"

                if m_name:
                    new_spot[str(m_idx)] = m_name
                    new_spot[f"@{m_idx}"] = m_name
                    new_spot[m_name] = m_name

    # Process Perps Meta
    if isinstance(perps_meta, dict):
        universe = perps_meta.get("universe", [])
        for idx, asset in enumerate(universe):
            name = asset.get("name")
            if name:
                new_perp[str(idx)] = name
                new_perp[name] = name

    _SYMBOL_CACHE["spot"] = new_spot
    _SYMBOL_CACHE["perp"] = new_perp
    _SYMBOL_CACHE["last_update"] = now
    logger.info(f"Refreshed symbol mapping. Spot: {len(new_spot)}, Perp: {len(new_perp)}")

async def get_symbol_name(token_id: str | int, is_spot: bool = False) -> str:
    """Resolves a token ID (or index) to its symbol name."""
    await ensure_symbol_mapping()
    
    s_id = str(token_id)
    
    # Auto-detect spot if it starts with @
    if s_id.startswith("@"):
        is_spot = True
        
    cache = _SYMBOL_CACHE["spot"] if is_spot else _SYMBOL_CACHE["perp"]
    
    # Check exact match in relevant cache
    if s_id in cache:
        return cache[s_id]
    
    # Handle @ID format specifically for spot if it wasn't in cache
    if is_spot and not s_id.startswith("@") and s_id.isdigit():
        at_id = f"@{s_id}"
        if at_id in cache:
            return cache[at_id]

    # Hardcoded overrides for canonical Perps (only if not spot)
    if not is_spot:
        if s_id == "0": return "BTC"
        if s_id == "1": return "ETH"
    
    # Check other cache as fallback? No, better be strict to avoid bugs.
    # But for safety with common names:
    if s_id in ("BTC", "ETH", "SOL", "HYPE", "USDC"):
        return s_id
        
    return s_id


def normalize_spot_coin(coin: str | None) -> str:
    if not coin:
        return ""
    c = str(coin).upper()
    if c == "USDC":
        return c
    # If it starts with U and followed by letters (e.g. UPURR), it might be internal name
    if c.startswith("U") and len(c) > 1 and not c[1].isdigit():
         return c[1:]
    return c

def _is_buy(side: str) -> bool:
    s = side.lower()
    return s in ("buy", "bid", "b")

def calc_avg_entry_from_fills(fills: list[dict]) -> float:
    """Calculates weighted average entry price from a list of fills."""
    if not fills:
        return 0.0

    fills_sorted = sorted(fills, key=lambda x: float(x.get("time", 0)))
    qty = 0.0
    cost = 0.0
    for f in fills_sorted:
        sz = float(f.get("sz", 0) or 0)
        px = float(f.get("px", 0) or 0)
        side = str(f.get("side", ""))
        
        if _is_buy(side):
            qty += sz
            cost += sz * px
        else:
            if qty <= 0:
                continue
            # Weighted average reduction
            sell_sz = min(sz, qty)
            avg_cost = cost / qty if qty > 0 else 0.0
            qty -= sell_sz
            cost -= avg_cost * sell_sz

    if qty > 0 and cost > 0:
        return cost / qty
    return 0.0

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

    # Spot fields from spotClearinghouseState (entryNtl / total)
    entry_ntl = balance.get("entryNtl")
    total = balance.get("total")
    if entry_ntl is not None and total is not None:
        try:
            e = float(entry_ntl)
            t = float(total)
            if t > 0:
                return e / t
        except (ValueError, TypeError):
            pass

    # Other potential fields
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
    """Fetch global perps market context (funding, prices, open interest)."""
    await _rate_limit()
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

_MIDS_CACHE = {
    "data": {},
    "last_update": 0
}

async def get_all_mids():
    now = time.time()
    if now - _MIDS_CACHE["last_update"] < 10 and _MIDS_CACHE["data"]:
        return _MIDS_CACHE["data"]

    url = f"{settings.HYPERLIQUID_API_URL}/info"
    payload = {"type": "allMids"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, dict):
                        # Hyperliquid returns a flat dict for allMids, not {"mids": ...}
                        # If it does have a 'mids' key, use it, otherwise use root.
                        mids = data.get("mids") if "mids" in data else data
                        if isinstance(mids, dict):
                            _MIDS_CACHE["data"] = mids
                            _MIDS_CACHE["last_update"] = now
                            return mids
                    return None
                logger.error(f"Error fetching allMids: {resp.status}")
                return None
    except Exception as e:
        logger.error(f"Exception in get_all_mids: {e}")
        return None

async def get_mid_price(symbol: str, original_id: str | None = None) -> float:
    if not symbol:
        return 0.0
    sym = symbol.upper()
    if sym == "USDC":
        return 1.0

    mids = await get_all_mids()
    if not mids:
        return 0.0

    # 1. Try original ID (e.g. "@1")
    if original_id and str(original_id) in mids:
        try:
            return float(mids[str(original_id)])
        except:
            pass

    # 2. Try symbol name (e.g. "PURR/USDC" or "BTC")
    if sym in mids:
        try:
            return float(mids[sym])
        except:
            pass
            
    # 3. Special case for Spot: if symbol is "PURR", allMids might have "PURR/USDC"
    if "/" not in sym:
        alt_sym = f"{sym}/USDC"
        if alt_sym in mids:
            try:
                return float(mids[alt_sym])
            except:
                pass

    return 0.0

async def get_user_portfolio(wallet_address: str):
    """Fetch historical PnL/Portfolio stats (Official API data)."""
    await _rate_limit()
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

async def get_user_funding(wallet_address: str, start_time: int = None):
    """Fetch user funding history."""
    url = f"{settings.HYPERLIQUID_API_URL}/info"
    payload = {
        "type": "userFundingHistory",
        "user": wallet_address
    }
    if start_time:
        payload["startTime"] = start_time
        
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                return await resp.json()
            return []

async def get_user_ledger(wallet_address: str, start_time: int = None):
    """Fetch user non-funding ledger updates (deposits, withdrawals, transfers)."""
    url = f"{settings.HYPERLIQUID_API_URL}/info"
    payload = {
        "type": "userNonFundingLedgerUpdates",
        "user": wallet_address
    }
    if start_time:
        payload["startTime"] = start_time

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                return await resp.json()
            return []

async def get_user_vault_equities(wallet_address: str):
    """Fetch user's equity in all vaults they participate in."""
    url = f"{settings.HYPERLIQUID_API_URL}/info"
    payload = {
        "type": "userVaultEquities",
        "user": wallet_address
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                return await resp.json()
            return []

async def get_hlp_info():
    """Fetch HLP vault details."""
    url = f"{settings.HYPERLIQUID_API_URL}/info"
    payload = {
        "type": "vaultDetails",
        "vaultAddress": "0xdf13098394e1832014b0df3f91285497",
        "user": "0x0000000000000000000000000000000000000000"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                return await resp.json()
            return None

async def get_all_assets_meta():
    """Fetch both spot and perps meta in one go."""
    spot, perps = await asyncio.gather(
        get_spot_meta(),
        get_perps_meta(),
        return_exceptions=True
    )
    return {
        "spot": spot if not isinstance(spot, Exception) else None,
        "perps": perps if not isinstance(perps, Exception) else None
    }

# Fear & Greed Index Cache
_FNG_CACHE = {
    "data": None,
    "last_update": 0
}

async def get_fear_greed_index():
    """
    Fetch Fear & Greed Index from Alternative.me API.
    Returns dict with: value (0-100), classification, timestamp, change from yesterday.
    Caches for 5 minutes.
    """
    now = time.time()
    if now - _FNG_CACHE["last_update"] < 300 and _FNG_CACHE["data"]:
        return _FNG_CACHE["data"]
    
    url = "https://api.alternative.me/fng/?limit=2"  # Get today + yesterday for change
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    fng_data = data.get("data", [])
                    
                    if len(fng_data) >= 1:
                        today = fng_data[0]
                        yesterday = fng_data[1] if len(fng_data) >= 2 else None
                        
                        value = int(today.get("value", 50))
                        classification = today.get("value_classification", "Neutral")
                        timestamp = int(today.get("timestamp", 0))
                        
                        # Calculate change
                        change = 0
                        if yesterday:
                            yesterday_val = int(yesterday.get("value", value))
                            change = value - yesterday_val
                        
                        result = {
                            "value": value,
                            "classification": classification,
                            "timestamp": timestamp,
                            "change": change,
                            "emoji": _fng_emoji(value)
                        }
                        
                        _FNG_CACHE["data"] = result
                        _FNG_CACHE["last_update"] = now
                        return result
                        
                logger.error(f"Error fetching Fear & Greed: {resp.status}")
                return None
    except Exception as e:
        logger.error(f"Exception fetching Fear & Greed: {e}")
        return None

def _fng_emoji(value: int) -> str:
    """Return emoji based on Fear & Greed value."""
    if value <= 20:
        return "😱"  # Extreme Fear
    elif value <= 40:
        return "😰"  # Fear
    elif value <= 60:
        return "😐"  # Neutral
    elif value <= 80:
        return "😊"  # Greed
    else:
        return "🤑"  # Extreme Greed

