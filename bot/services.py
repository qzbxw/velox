import aiohttp
import logging
from bot.config import settings

logger = logging.getLogger(__name__)

def normalize_spot_coin(coin: str | None) -> str:
    if not coin:
        return ""
    c = str(coin).upper()
    if c == "USDC":
        return c
    if c.startswith("U") and len(c) > 1:
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
    """Best-effort: try to use avg/entry provided by spotClearinghouseState.

    Hyperliquid spot balance objects can vary; we probe common fields.
    Returns 0.0 if not available.
    """
    if not isinstance(balance, dict):
        return 0.0

    # direct average fields
    for k in ("avgPx", "avg_px", "avgPrice", "entryPx", "entry_px", "avgEntry"):
        v = balance.get(k)
        if v is not None:
            try:
                px = float(v)
                if px > 0:
                    return px
            except (TypeError, ValueError):
                pass

    # entry notional / cost basis divided by position size
    total = balance.get("total")
    for k in ("entryNtl", "entry_ntl", "cost", "costBasis", "cost_basis"):
        v = balance.get(k)
        if v is None:
            continue
        try:
            ntl = float(v)
            sz = float(total) if total is not None else 0.0
            if ntl > 0 and sz > 0:
                return ntl / sz
        except (TypeError, ValueError):
            pass

    # nested objects
    inner = balance.get("position")
    if isinstance(inner, dict):
        return extract_avg_entry_from_balance(inner)

    return 0.0

def _extract_spot_balances(state: dict) -> list[dict]:
    if not isinstance(state, dict):
        return []
    balances = state.get("balances")
    if isinstance(balances, list):
        return balances
    inner = state.get("state")
    if isinstance(inner, dict) and isinstance(inner.get("balances"), list):
        return inner["balances"]
    return []

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

async def get_spot_balances(wallet_address: str) -> list[dict]:
    state = await get_user_state(wallet_address)
    return _extract_spot_balances(state)

async def get_spot_meta():
    """Fetch spot metadata (universe)."""
    url = f"{settings.HYPERLIQUID_API_URL}/info"
    payload = {"type": "spotMeta"}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                return await resp.json()
            return None

def extract_spot_symbol_map(spot_meta: dict) -> dict[int, str]:
    out: dict[int, str] = {}

    def walk(obj):
        if isinstance(obj, dict):
            name = obj.get("name")
            idx = obj.get("index")
            if isinstance(name, str) and isinstance(idx, int):
                out[idx] = name

            # common id keys
            name = obj.get("name")
            idx2 = obj.get("id")
            if isinstance(name, str) and isinstance(idx2, int):
                out[idx2] = name

            name = obj.get("name")
            tid = obj.get("tokenId")
            if isinstance(name, str) and isinstance(tid, int):
                out[tid] = name

            name = obj.get("name")
            coin_id = obj.get("coin")
            if isinstance(name, str) and isinstance(coin_id, int):
                out[coin_id] = name

            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for it in obj:
                walk(it)

    walk(spot_meta)

    # positional mapping for universe arrays (sometimes coin is an index)
    if isinstance(spot_meta, dict) and isinstance(spot_meta.get("universe"), list):
        universe = spot_meta.get("universe")
        for i, item in enumerate(universe):
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                out.setdefault(i, item["name"])

    if isinstance(spot_meta, dict) and isinstance(spot_meta.get("spotMeta"), dict):
        inner = spot_meta.get("spotMeta")
        if isinstance(inner.get("universe"), list):
            for i, item in enumerate(inner["universe"]):
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    out.setdefault(i, item["name"])

    return out

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

    px = mids.get(sym)
    if px is None and sym.startswith("U") and len(sym) > 1:
        px = mids.get(sym[1:])
    try:
        return float(px) if px is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
