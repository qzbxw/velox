import asyncio
import json
import logging
import time
import html
import websockets
from collections import defaultdict
from collections import deque
from bot.config import settings
from bot.database import db
from bot.services import extract_spot_symbol_map, get_open_orders, get_spot_meta, normalize_spot_coin

logger = logging.getLogger(__name__)

class WSManager:
    def __init__(self, bot):
        self.bot = bot
        self.ws_url = settings.HYPERLIQUID_WS_URL
        self.running = False
        self.ws = None
        self.tracked_wallets = set()
        self.mid_prices = {}  # {coin: price}
        self.last_mids_update_ts = 0.0
        self.open_orders = defaultdict(list)  # {wallet: [orders]}

        # Spot whitelist (from spotMeta). If empty -> no filtering.
        self.spot_coins = set()

        self.spot_symbol_map: dict[int, str] = {}

        # Market history + watchlist
        self.price_history = defaultdict(lambda: deque())  # symbol -> deque[(ts, px)]
        self.watch_subscribers = defaultdict(set)  # symbol -> set(chat_id)
        self.watch_alert_cooldowns = {}  # (chat_id, symbol) -> ts
        
        # Debounce: { (wallet, coin): timestamp }
        self.alert_cooldowns = {}
        
        # Task handles
        self.ping_task = None

    async def start(self):
        self.running = True
        while self.running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    self.ws = ws
                    logger.info("Connected to Hyperliquid WS")

                    await self._load_spot_universe()
                    
                    # Initial subscriptions
                    await self.subscribe_all_mids()
                    
                    # Load and subscribe users
                    users = await db.get_all_users()
                    for user in users:
                        wallet = user.get("wallet_address")
                        if wallet:
                            self.track_wallet(wallet)
                            await self._seed_open_orders(wallet)
                            await self.subscribe_user(wallet)

                        chat_id = user.get("chat_id")
                        if chat_id:
                            wl = user.get("watchlist")
                            if isinstance(wl, list):
                                for sym in wl:
                                    if isinstance(sym, str) and sym:
                                        self.watch_subscribers[sym.upper()].add(chat_id)
                            else:
                                # default
                                self.watch_subscribers["BTC"].add(chat_id)
                                self.watch_subscribers["ETH"].add(chat_id)
                            
                    # Start Ping loop
                    self.ping_task = asyncio.create_task(self._ping_loop())

                    async for message in ws:
                        await self.handle_message(json.loads(message))
                        
            except Exception as e:
                logger.error(f"WS Connection error: {e}")
                await asyncio.sleep(5)  # Backoff
            finally:
                if self.ping_task:
                    self.ping_task.cancel()

    async def _load_spot_universe(self):
        try:
            meta = await get_spot_meta()
            if isinstance(meta, dict):
                try:
                    self.spot_symbol_map = extract_spot_symbol_map(meta)
                except Exception:
                    self.spot_symbol_map = {}
            coins: set[str] = set()
            # spotMeta response shape can vary; try best-effort extraction.
            if isinstance(meta, dict):
                # common: { "universe": [{"name": "ETH"}, ...] }
                universe = meta.get("universe")
                if isinstance(universe, list):
                    for item in universe:
                        if isinstance(item, dict):
                            name = item.get("name")
                            if isinstance(name, str) and name:
                                coins.add(name)
                # other variants may nest
                inner = meta.get("spotMeta") or meta.get("data")
                if isinstance(inner, dict) and isinstance(inner.get("universe"), list):
                    for item in inner["universe"]:
                        if isinstance(item, dict):
                            name = item.get("name")
                            if isinstance(name, str) and name:
                                coins.add(name)

            if coins:
                self.spot_coins = coins
                logger.info(f"Loaded spot universe: {len(self.spot_coins)} coins")
            else:
                logger.warning("Could not parse spotMeta universe; spot filtering disabled")
        except Exception as e:
            logger.warning(f"Failed to load spotMeta: {e}")

    def _resolve_coin_symbol(self, coin):
        if coin is None:
            return None
        if isinstance(coin, int):
            sym = self.spot_symbol_map.get(coin)
            if sym:
                return normalize_spot_coin(sym)
            logger.warning(f"Unknown spot coin id: {coin}")
            return str(coin)
        if isinstance(coin, str):
            if coin.isdigit():
                try:
                    cid = int(coin)
                except ValueError:
                    return coin
                sym = self.spot_symbol_map.get(cid)
                if sym:
                    return normalize_spot_coin(sym)
                logger.warning(f"Unknown spot coin id: {coin}")
                return coin
            return normalize_spot_coin(coin)
        return str(coin)

    async def _seed_open_orders(self, wallet: str):
        try:
            data = await get_open_orders(wallet)
            if isinstance(data, dict):
                orders = data.get("orders")
                if isinstance(orders, list):
                    self.open_orders[wallet] = orders
        except Exception as e:
            logger.warning(f"Failed to seed open orders for {wallet}: {e}")

    async def _ping_loop(self):
        while self.running:
            await asyncio.sleep(50)
            if self.ws:
                try:
                    await self.ws.send(json.dumps({"method": "ping"}))
                except:
                    pass

    def get_price(self, coin: str) -> float:
        if not coin:
            return 0.0
        if coin == "USDC":
            return 1.0
        px = self.mid_prices.get(coin)
        if px is not None:
            return float(px)
        if coin.startswith("U") and len(coin) > 1:
            px = self.mid_prices.get(coin[1:])
            if px is not None:
                return float(px)
        return 0.0

    def _extract_order_fields(self, order: dict):
        if not isinstance(order, dict):
            return None, None
        if isinstance(order.get("order"), dict):
            order = order.get("order")

        coin = self._resolve_coin_symbol(order.get("coin"))
        limit_px = (
            order.get("limit_px")
            or order.get("limitPx")
            or order.get("limitpx")
            or order.get("px")
        )
        return coin, limit_px

    def _extract_order_side(self, order: dict) -> str:
        if not isinstance(order, dict):
            return ""
        if isinstance(order.get("order"), dict):
            order = order.get("order")
        side = str(order.get("side", "")).lower()
        if side in ("b", "buy", "bid"):
            return "buy"
        if side in ("a", "s", "sell", "ask"):
            return "sell"
        return ""

    def _extract_order_size(self, order: dict) -> float:
        if not isinstance(order, dict):
            return 0.0
        if isinstance(order.get("order"), dict):
            order = order.get("order")
        sz = order.get("sz") or order.get("size") or order.get("origSz") or order.get("orig_sz")
        try:
            return float(sz) if sz is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _extract_order_id(self, order: dict):
        if not isinstance(order, dict):
            return None
        if isinstance(order.get("order"), dict):
            order = order.get("order")
        return (
            order.get("oid")
            or order.get("orderId")
            or order.get("id")
        )

    def _is_spot_coin(self, coin: str | None) -> bool:
        coin = self._resolve_coin_symbol(coin)
        if not coin:
            return False
        if not self.spot_coins:
            return True
        if coin in self.spot_coins:
            return True
        # Some APIs prefix spot assets with U
        if coin.startswith("U") and coin[1:] in self.spot_coins:
            return True
        return False

    def track_wallet(self, wallet: str):
        self.tracked_wallets.add(wallet)
        logger.info(f"Now tracking wallet: {wallet}")

    def untrack_wallet(self, wallet: str):
        self.tracked_wallets.discard(wallet)
        # Clear cached data for this wallet
        self.open_orders.pop(wallet, None)
        # Remove cooldowns for this wallet
        keys_to_remove = [k for k in self.alert_cooldowns if k[0] == wallet]
        for k in keys_to_remove:
            del self.alert_cooldowns[k]
        logger.info(f"Stopped tracking wallet: {wallet}")

    def get_open_orders_cached(self, wallet: str) -> list:
        return list(self.open_orders.get(wallet, []))

    async def subscribe_user(self, wallet):
        if not self.ws: return
        # User Fills
        await self.ws.send(json.dumps({
            "method": "subscribe",
            "subscription": {"type": "userFills", "user": wallet}
        }))
        # Open Orders
        await self.ws.send(json.dumps({
            "method": "subscribe",
            "subscription": {"type": "openOrders", "user": wallet}
        }))
        logger.info(f"Subscribed to updates for {wallet}")

    async def subscribe_all_mids(self):
        if not self.ws: return
        await self.ws.send(json.dumps({
            "method": "subscribe",
            "subscription": {"type": "allMids"}
        }))

    async def handle_message(self, data):
        channel = data.get("channel")
        
        if channel == "allMids":
            await self.handle_mids(data.get("data", {}).get("mids", {}))
        elif channel == "userFills":
            await self.handle_fills(data.get("data", {}))
        elif channel == "openOrders":
            await self.handle_open_orders(data.get("data", [])) # Verify format
        elif channel == "subscriptionResponse":
            pass # Acknowledge
        elif channel == "pong":
            pass

    async def handle_mids(self, mids):
        # Update local cache
        for coin, price in mids.items():
            self.mid_prices[coin] = float(price)

        self.last_mids_update_ts = time.time()

        await self._update_market_history_and_alerts()
            
        # Check proximity
        await self.check_proximity()

    async def _update_market_history_and_alerts(self):
        now = time.time()
        symbols = set(self.watch_subscribers.keys()) | {"BTC", "ETH"}
        max_age = settings.MARKET_HISTORY_MINUTES * 60

        for sym in symbols:
            px = self.get_price(sym)
            if not px:
                continue
            dq = self.price_history[sym]
            dq.append((now, float(px)))
            while dq and (now - dq[0][0]) > max_age:
                dq.popleft()

        await self._check_watch_alerts(now)

    def _price_at_or_before(self, sym: str, target_ts: float):
        dq = self.price_history.get(sym)
        if not dq:
            return None
        last = None
        for ts, px in dq:
            if ts <= target_ts:
                last = px
            else:
                break
        return last

    def get_market_snapshot(self, sym: str):
        sym = (sym or "").upper()
        dq = self.price_history.get(sym)
        if not dq:
            return None
        now_ts, now_px = dq[-1]

        def change_for(window_sec: int):
            ref = self._price_at_or_before(sym, now_ts - window_sec)
            if not ref or not now_px:
                return None
            return ((now_px / ref) - 1.0) * 100.0

        def vol_for(window_sec: int):
            lo = None
            hi = None
            start_ts = now_ts - window_sec
            for ts, px in dq:
                if ts < start_ts:
                    continue
                lo = px if lo is None else min(lo, px)
                hi = px if hi is None else max(hi, px)
            if lo is None or hi is None or lo == 0:
                return None
            return ((hi / lo) - 1.0) * 100.0

        return {
            "px": now_px,
            "chg_1m": change_for(60),
            "chg_5m": change_for(300),
            "chg_15m": change_for(900),
            "vol_1m": vol_for(60),
            "vol_5m": vol_for(300),
            "vol_15m": vol_for(900),
        }

    async def _check_watch_alerts(self, now: float):
        window = settings.WATCH_ALERT_WINDOW_SEC
        thresh = settings.WATCH_ALERT_PCT
        for sym, subs in self.watch_subscribers.items():
            if not subs:
                continue
            cur = self.get_price(sym)
            if not cur:
                continue
            ref = self._price_at_or_before(sym, now - window)
            if not ref:
                continue
            move = (float(cur) / float(ref)) - 1.0
            if abs(move) < thresh:
                continue

            direction = "📈" if move > 0 else "📉"
            for chat_id in list(subs):
                key = (chat_id, sym)
                last = self.watch_alert_cooldowns.get(key, 0)
                if now - last < settings.WATCH_ALERT_COOLDOWN:
                    continue
                self.watch_alert_cooldowns[key] = now

                lang = "ru"
                try:
                    lang = await db.get_lang(chat_id)
                except Exception:
                    lang = "ru"

                title = "<b>Watch Alert</b>" if lang == "en" else "<b>Алерт: Watchlist</b>"
                moved = "moved" if lang == "en" else "двинулся"
                in_txt = "in" if lang == "en" else "за"
                now_lbl = "Now" if lang == "en" else "Сейчас"
                then_lbl = "Then" if lang == "en" else "Было"

                msg = (
                    f"{direction} {title}\n"
                    f"<b>{sym}</b> {moved} <b>{move*100:+.2f}%</b> {in_txt} <b>{window//60}m</b>\n"
                    f"{now_lbl}: <b>${float(cur):.4f}</b>\n"
                    f"{then_lbl}: <b>${float(ref):.4f}</b>"
                )
                try:
                    await self.bot.send_message(chat_id, msg, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Failed to send watch alert: {e}")

    async def check_proximity(self):
        # For each wallet, check open orders against current mid price
        for wallet, orders in self.open_orders.items():
            for order in orders:
                coin, limit_px_raw = self._extract_order_fields(order)
                if not self._is_spot_coin(coin):
                    continue
                if not coin or limit_px_raw is None:
                    continue
                try:
                    limit_px = float(limit_px_raw)
                except (TypeError, ValueError):
                    continue
                current_px = self.get_price(coin)
                
                if not current_px: continue
                
                side = self._extract_order_side(order)
                sz = self._extract_order_size(order)

                pct_thresh = settings.PROXIMITY_THRESHOLD
                if side == "buy":
                    pct_thresh = settings.BUY_PROXIMITY_THRESHOLD
                elif side == "sell":
                    pct_thresh = settings.SELL_PROXIMITY_THRESHOLD

                diff = abs(current_px - limit_px)
                pct_diff = (diff / limit_px) if limit_px else 0.0
                usd_diff = diff * sz if sz else 0.0

                hit_pct = pct_diff <= pct_thresh if pct_thresh else False
                hit_usd = usd_diff <= settings.PROXIMITY_USD_THRESHOLD if (settings.PROXIMITY_USD_THRESHOLD and sz) else False

                if hit_pct or hit_usd:
                    oid = self._extract_order_id(order)
                    await self.trigger_proximity_alert(wallet, coin, limit_px, current_px, oid, side, sz, pct_diff, usd_diff)

    async def trigger_proximity_alert(self, wallet, coin, limit_px, current_px, oid=None, side="", sz=0.0, pct_diff=0.0, usd_diff=0.0):
        # Check cooldown
        key = (wallet, coin, oid or "")
        last_alert = self.alert_cooldowns.get(key, 0)
        if time.time() - last_alert < settings.ALERT_COOLDOWN:
            return
            
        self.alert_cooldowns[key] = time.time()
        
        # Notify users tracking this wallet
        users = await db.get_users_by_wallet(wallet)
        for user in users:
            chat_id = user.get('chat_id')
            lang = "ru"
            try:
                if chat_id:
                    lang = await db.get_lang(chat_id)
            except Exception:
                lang = "ru"

            safe_coin = html.escape(str(coin))
            side_txt = "🟢 BUY" if side == "buy" else ("🔴 SELL" if side == "sell" else "🟡 ORDER")
            dir_txt = "↓" if side == "buy" else ("↑" if side == "sell" else "")
            pct_thresh = settings.PROXIMITY_THRESHOLD
            if side == "buy":
                pct_thresh = settings.BUY_PROXIMITY_THRESHOLD
            elif side == "sell":
                pct_thresh = settings.SELL_PROXIMITY_THRESHOLD

            title = "⚠️ <b>Proximity Alert</b>" if lang == "en" else "⚠️ <b>Алерт: Proximity</b>"
            mid_lbl = "Mid" if lang == "en" else "Mid"
            limit_lbl = "Limit" if lang == "en" else "Лимит"
            to_fill_lbl = "To fill" if lang == "en" else "До исполнения"
            diff_lbl = "Diff" if lang == "en" else "Отклонение"
            usd_lbl = "USD dist" if lang == "en" else "USD дистанция"

            msg = (
                f"{title}\n"
                f"{side_txt} {safe_coin}\n"
                f"{mid_lbl}: <b>{current_px:.6f}</b>\n"
                f"{limit_lbl}: <b>{limit_px:.6f}</b>\n"
                f"{to_fill_lbl}: {dir_txt} {(abs(current_px - limit_px) / current_px) * 100:.2f}%\n"
                f"{diff_lbl}: {pct_diff*100:.2f}% (thr {pct_thresh*100:.2f}%)\n"
                + (f"{usd_lbl}: ${usd_diff:.2f} (thr ${settings.PROXIMITY_USD_THRESHOLD:.2f})\n" if sz else "")
                + f"Wallet: <code>{wallet[:6]}...{wallet[-4:]}</code>"
            )
            try:
                await self.bot.send_message(chat_id, msg, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Failed to send alert to {chat_id}: {e}")

    async def handle_fills(self, data):
        # data format: { isSnapshot: bool, user: str, fills: [WsFill] }
        user_wallet = data.get("user")
        fills = data.get("fills", [])
        
        # If snapshot, maybe we just store history but don't alert?
        # Prompt says "User Fills: Subscribe to user events... send an instant notification"
        # Usually snapshots are initial state. We might want to skip alerting on snapshot 
        # to avoid spamming old fills on restart.
        if data.get("isSnapshot"):
            logger.info(f"Received snapshot for {user_wallet} with {len(fills)} fills (no alerts)")
            # Store fills silently
            for fill in fills:
                fill_with_user = dict(fill)
                fill_with_user["user"] = user_wallet
                await db.add_fill(fill_with_user)
            return
        
        # Notify users tracking this wallet
        users = await db.get_users_by_wallet(user_wallet)
        for user in users:
            chat_id = user.get('chat_id')
            lang = "ru"
            try:
                if chat_id:
                    lang = await db.get_lang(chat_id)
            except Exception:
                lang = "ru"
            
            for fill in fills:
                coin = fill.get("coin")
                side = fill.get("side")
                px = fill.get("px")
                sz = fill.get("sz")
                if not all([coin, side, px, sz]):
                    continue
                
                # Only spot coins
                norm_coin = normalize_spot_coin(coin)
                if not self._is_spot_coin(norm_coin):
                    continue
                
                # Store fill
                fill_with_user = dict(fill)
                fill_with_user["user"] = user_wallet
                await db.add_fill(fill_with_user)
                
                side_emoji = "🟢" if side.lower() in ("b","buy","bid") else "🔴"
                safe_coin = html.escape(str(norm_coin))
                wallet_tag = f"{user_wallet[:6]}...{user_wallet[-4:]}"
                msg = (
                    f"{side_emoji} <b>Fill</b>\n"
                    f"<b>{safe_coin}</b>\n"
                    f"{side_emoji} {side.upper()} {sz:.6f} @ ${float(px):.6f}\n"
                    f"Wallet: <code>{wallet_tag}</code>"
                )
                try:
                    await self.bot.send_message(chat_id, msg, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Failed to send fill notification to {chat_id}: {e}")

    async def handle_open_orders(self, data):
        # data format for openOrders subscription?
        # Docs: "Data format: OpenOrders".
        # Interface OpenOrders { dex: string, user: string, orders: Array<Order> }
        # Need to check if 'data' is the OpenOrders object or list of orders.
        # Docs say: "The data field providing the subscribed data." -> "Data format: OpenOrders"
        
        orders = []
        if isinstance(data, list):
            orders = data # In case it's just a list
        elif isinstance(data, dict):
             orders = data.get("orders", [])
             
        user_wallet = data.get("user") if isinstance(data, dict) else None
        # If we can't find user in data, we might need to rely on tracking contexts, 
        # but 'user' is in the OpenOrders object.
        
        if user_wallet:
            # Filter to spot coins if we were able to load spot universe.
            if self.spot_coins:
                filtered = []
                for o in orders:
                    coin, _ = self._extract_order_fields(o)
                    if self._is_spot_coin(coin):
                        filtered.append(o)
                self.open_orders[user_wallet] = filtered
            else:
                self.open_orders[user_wallet] = orders
