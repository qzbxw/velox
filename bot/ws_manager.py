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
from bot.services import get_open_orders, get_spot_meta, normalize_spot_coin, pretty_float, get_symbol_name

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

        # All known symbols (Spot + Perps)
        self.all_coins = set()
        
        # Market history + watchlist
        self.price_history = defaultdict(lambda: deque())  # symbol -> deque[(ts, px)]
        self.watch_subscribers = defaultdict(set)  # symbol -> set(chat_id)
        self.watch_alert_cooldowns = {}  # (chat_id, symbol) -> ts
        
        # Debounce: { (wallet, coin): timestamp }
        self.alert_cooldowns = {}
        
        # Custom Price Alerts (User defined)
        self.active_alerts = [] # List of alert dicts
        self.triggered_alerts = set() # Set of alert_ids that recently triggered (to avoid double trigger if DB lag)
        
        # Task handles
        self.ping_task = None
        self.alerts_refresh_task = None

    async def start(self):
        self.running = True
        
        # Start background tasks
        self.alerts_refresh_task = asyncio.create_task(self._refresh_alerts_loop())
        
        while self.running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    self.ws = ws
                    logger.info("Connected to Hyperliquid WS")

                    await self._load_universe()
                    
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
        
        if self.alerts_refresh_task:
            self.alerts_refresh_task.cancel()

    async def _load_universe(self):
        try:
            from bot.services import get_perps_meta
            spot_meta, perps_meta = await asyncio.gather(
                get_spot_meta(),
                get_perps_meta(),
                return_exceptions=True
            )
            
            coins: set[str] = set()
            # Spot
            if isinstance(spot_meta, dict):
                universe = spot_meta.get("universe", [])
                for item in universe:
                    if isinstance(item, dict) and item.get("name"):
                        coins.add(item["name"])
            
            # Perps
            if isinstance(perps_meta, dict):
                universe = perps_meta.get("universe", [])
                for item in universe:
                    if isinstance(item, dict) and item.get("name"):
                        coins.add(item["name"])

            if coins:
                self.all_coins = coins
                logger.info(f"Loaded universe: {len(self.all_coins)} assets")
        except Exception as e:
            logger.warning(f"Failed to load universe: {e}")

    def _resolve_coin_symbol(self, coin):
        if coin is None:
            return None
        return normalize_spot_coin(str(coin))

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

    async def _refresh_alerts_loop(self):
        """Fetch alerts from DB periodically."""
        while self.running:
            try:
                alerts = await db.get_all_active_alerts()
                if alerts is not None:
                    self.active_alerts = alerts
            except Exception as e:
                logger.error(f"Error refreshing alerts: {e}")
            await asyncio.sleep(10)

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

    def _is_known_coin(self, coin: str | None) -> bool:
        coin = self._resolve_coin_symbol(coin)
        if not coin:
            return False
        if not self.all_coins:
            return True
        if coin in self.all_coins:
            return True
        if coin.startswith("U") and coin[1:] in self.all_coins:
            return True
        return False

    def track_wallet(self, wallet: str):
        wallet = wallet.lower()
        self.tracked_wallets.add(wallet)
        logger.info(f"Now tracking wallet: {wallet}")

    def untrack_wallet(self, wallet: str):
        wallet = wallet.lower()
        self.tracked_wallets.discard(wallet)
        self.open_orders.pop(wallet, None)
        keys_to_remove = [k for k in self.alert_cooldowns if k[0] == wallet]
        for k in keys_to_remove:
            del self.alert_cooldowns[k]
        logger.info(f"Stopped tracking wallet: {wallet}")

    def get_open_orders_cached(self, wallet: str) -> list:
        return list(self.open_orders.get(wallet.lower(), []))

    async def subscribe_user(self, wallet):
        if not self.ws: return
        wallet = wallet.lower()
        await self.ws.send(json.dumps({
            "method": "subscribe",
            "subscription": {"type": "userFills", "user": wallet}
        }))
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
            await self.handle_open_orders(data.get("data", []))

    async def handle_mids(self, mids):
        for coin, price in mids.items():
            self.mid_prices[coin] = float(price)

        self.last_mids_update_ts = time.time()
        await self._update_market_history_and_alerts()
        await self.check_proximity()
        await self._check_custom_alerts() # Check user defined alerts

    async def _check_custom_alerts(self):
        """Check all active custom alerts against current prices."""
        for alert in self.active_alerts:
            aid = str(alert.get("_id"))
            if aid in self.triggered_alerts:
                continue
                
            symbol = alert.get("symbol")
            target = alert.get("price")
            direction = alert.get("direction") # above / below
            user_id = alert.get("user_id")
            
            current_price = self.get_price(symbol)
            if not current_price:
                continue
                
            triggered = False
            if direction == "above" and current_price >= target:
                triggered = True
            elif direction == "below" and current_price <= target:
                triggered = True
                
            if triggered:
                # Fire alert
                self.triggered_alerts.add(aid)
                # Remove from DB
                await db.delete_alert(aid)
                # Send message
                msg = f"🔔 <b>Alert: {html.escape(symbol)}</b>\n\nPrice hit <b>${pretty_float(current_price)}</b> (Target: {direction} {target})"
                try:
                    await self.bot.send_message(user_id, msg, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Failed to send alert to {user_id}: {e}")

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
        for wallet, orders in self.open_orders.items():
            for order in orders:
                coin, limit_px_raw = self._extract_order_fields(order)
                if not self._is_known_coin(coin):
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
        key = (wallet, coin, oid or "")
        last_alert = self.alert_cooldowns.get(key, 0)
        if time.time() - last_alert < settings.ALERT_COOLDOWN:
            return
        self.alert_cooldowns[key] = time.time()
        
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
        user_wallet = data.get("user")
        if user_wallet:
            user_wallet = user_wallet.lower()
        
        fills = data.get("fills", [])
        
        if data.get("isSnapshot"):
            logger.info(f"Received snapshot for {user_wallet} with {len(fills)} fills (no alerts)")
            for fill in fills:
                fill_with_user = dict(fill)
                fill_with_user["user"] = user_wallet
                await db.save_fill(fill_with_user)
            return
        
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
                
                norm_coin = normalize_spot_coin(coin)
                if not self._is_known_coin(norm_coin):
                    continue
                
                fill_with_user = dict(fill)
                fill_with_user["user"] = user_wallet
                await db.save_fill(fill_with_user)
                
                # Check for liquidation
                is_liq = fill.get("liquidation", False) or fill.get("isLiquidation", False)
                
                side_emoji = "🟢" if side.lower() in ("b","buy","bid") else "🔴"
                if is_liq:
                    side_emoji = "💀"
                
                safe_coin = html.escape(str(norm_coin))
                wallet_tag = f"{user_wallet[:6]}...{user_wallet[-4:]}"
                
                type_lbl = "Fill" if lang == "en" else "Исполнение"
                if is_liq:
                    type_lbl = "LIQUIDATION" if lang == "en" else "ЛИКВИДАЦИЯ"

                msg = (
                    f"{side_emoji} <b>{type_lbl}</b>\n"
                    f"<b>{safe_coin}</b>\n"
                    f"{side_emoji} {side.upper()} {sz:.6f} @ ${float(px):.6f}\n"
                    f"Wallet: <code>{wallet_tag}</code>"
                )
                try:
                    await self.bot.send_message(chat_id, msg, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Failed to send fill notification to {chat_id}: {e}")

    async def handle_open_orders(self, data):
        orders = []
        if isinstance(data, list):
            orders = data
        elif isinstance(data, dict):
             orders = data.get("orders", [])
             
        user_wallet = data.get("user") if isinstance(data, dict) else None
        if user_wallet:
            user_wallet = user_wallet.lower()

        if user_wallet:
            if self.all_coins:
                filtered = []
                for o in orders:
                    coin, _ = self._extract_order_fields(o)
                    if self._is_known_coin(coin):
                        filtered.append(o)
                self.open_orders[user_wallet] = filtered
            else:
                self.open_orders[user_wallet] = orders