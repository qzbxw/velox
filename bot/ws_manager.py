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
from bot.locales import _t
from bot.services import get_open_orders, get_spot_meta, normalize_spot_coin, pretty_float, get_symbol_name, get_perps_context, get_hlp_info
from bot.renderer import render_html_to_image
from bot.analytics import prepare_modern_market_data, prepare_liquidity_data
from aiogram.types import BufferedInputFile, InputMediaPhoto

logger = logging.getLogger(__name__)

class WSManager:
    def __init__(self, bot):
        self.bot = bot
        self.ws_url = settings.HYPERLIQUID_WS_URL
        self.running = False
        self.ws = None
        
        # Data caches
        self.mid_prices = {}  # symbol/id -> price
        self.open_orders = defaultdict(list)  # wallet -> [orders]
        self.tracked_wallets = set()
        
        # All known symbols (Spot + Perps)
        self.all_coins = set()
        
        # Market history + watchlist
        self.price_history = defaultdict(lambda: deque())  # symbol -> deque[(ts, px)]
        self.watch_subscribers = defaultdict(set)  # symbol -> set(chat_id)
        self.watch_alert_cooldowns = {}  # (chat_id, symbol) -> ts
        
        # Debounce: { (wallet, coin): timestamp }
        self.alert_cooldowns = {}
        
        # Liquidation Alert Cooldown: { wallet: timestamp }
        self.liq_alert_cooldowns = {}
        
        # Custom Price Alerts (User defined)
        self.active_alerts = [] # List of alert dicts
        self.triggered_alerts = set() # Set of alert_ids that recently triggered (to avoid double trigger if DB lag)
        
        # Task handles
        self.ping_task = None
        self.alerts_refresh_task = None
        self.whale_task = None
        self.listing_check_task = None
        self.ledger_task = None
        
        # Market Stats for Alerts
        self.asset_ctx_cache = {} # sym -> ctx data
        
        # Whale Watcher
        self.top_assets = set()
        self.whale_cache = deque(maxlen=20) # Dedup recent large trades
        self.whale_subscribers_cache = [] # List of user docs

    async def fire_hedge_insight(self, chat_id, user_id, context_type, event_data, reply_to_id=None):
        from bot.handlers import _send_hedge_insight
        asyncio.create_task(_send_hedge_insight(self.bot, chat_id, user_id, context_type, event_data, reply_to_id))

    async def start(self):
        self.running = True
        
        # Start background tasks
        self.alerts_refresh_task = asyncio.create_task(self._refresh_alerts_loop())
        self.whale_task = asyncio.create_task(self._whale_assets_loop())
        self.listing_check_task = asyncio.create_task(self._listing_monitor_loop())
        self.ledger_task = asyncio.create_task(self._ledger_loop())
        
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
                        # Legacy primary wallet
                        wallet = user.get("wallet_address")
                        if wallet:
                            self.track_wallet(wallet)
                            await self._seed_open_orders(wallet)
                            await self.subscribe_user(wallet)
                            await asyncio.sleep(0.05) # Small delay to prevent rate limit

                        chat_id = user.get("chat_id") or user.get("user_id")
                        if chat_id:
                            wl = user.get("watchlist")
                            if isinstance(wl, list):
                                for sym in wl:
                                    if isinstance(sym, str) and sym:
                                        self.watch_subscribers[sym.upper()].add(chat_id)
                    
                    # Also load from dedicated wallets collection
                    cursor = db.wallets.find({})
                    async for w_doc in cursor:
                        wallet = w_doc.get("address")
                        if wallet:
                            self.track_wallet(wallet)
                            await self._seed_open_orders(wallet)
                            await self.subscribe_user(wallet)
                            await asyncio.sleep(0.05)
                            
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
        if self.whale_task:
            self.whale_task.cancel()

    async def _whale_assets_loop(self):
        """Periodically subscribe to trades for top volume assets."""
        while self.running:
            try:
                if not self.ws:
                    await asyncio.sleep(5)
                    continue

                ctx = await get_perps_context()
                if ctx and isinstance(ctx, list) and len(ctx) == 2:
                    universe = ctx[0]["universe"]
                    asset_ctxs = ctx[1]
                    
                    # Sort by volume (dayNtlVlm)
                    # asset_ctxs is same order as universe
                    combined = []
                    for i, u in enumerate(universe):
                        if i < len(asset_ctxs):
                            vol = float(asset_ctxs[i].get("dayNtlVlm", 0))
                            combined.append((u["name"], vol))
                    
                    combined.sort(key=lambda x: x[1], reverse=True)
                    top_20 = [x[0] for x in combined[:20]]
                    
                    # Subscribe to new ones
                    new_assets = set(top_20)
                    to_sub = new_assets - self.top_assets
                    
                    if to_sub:
                        logger.info(f"Whale Watcher: Subscribing to {len(to_sub)} assets")
                        for sym in to_sub:
                            await self.ws.send(json.dumps({
                                "method": "subscribe",
                                "subscription": {"type": "trades", "coin": sym}
                            }))
                            await asyncio.sleep(0.1) # Rate limit
                    
                    self.top_assets = new_assets
                    
            except Exception as e:
                logger.error(f"Whale loop error: {e}")
            
            await asyncio.sleep(300) # Refresh every 5 min

    async def handle_trades(self, data):
        """Handle public trades for Whale Watcher."""
        trades = data.get("data", [])
        if not trades: return
        
        # Use cached subscribers
        whale_users = self.whale_subscribers_cache
        if not whale_users: return

        for t in trades:
            sym = t.get("coin")
            if not sym: continue 
            
            sz = float(t.get("sz", 0))
            px = float(t.get("px", 0))
            val = sz * px
            
            # Global min threshold to even bother ($50k)
            if val < 50_000: continue
            
            # Dedup
            tid = t.get("hash") or f"{sym}-{t.get('time')}-{sz}"
            if tid in self.whale_cache: continue
            self.whale_cache.append(tid)
            
            side = t.get("side", "").upper()
            icon = "🟢" if side == "B" else "🔴"
            side_txt = "BUY" if side == "B" else "SELL"
            
            for u in whale_users:
                user_id = u.get("user_id")
                # Check user specific threshold if any
                thr = u.get("whale_threshold", 50_000)
                if val < thr: continue

                # Watchlist filter
                if u.get("whale_watchlist_only"):
                    watchlist = await db.get_watchlist(user_id)
                    if sym not in watchlist:
                        continue
                    
                try:
                    lang = u.get("lang", "ru")
                    msg = _t(lang, "whale_alert") + "\n" + _t(lang, "whale_msg", icon=icon, side=side_txt, symbol=sym, val=pretty_float(val, 0), price=pretty_float(px))
                    sent_msg = await self.bot.send_message(user_id, msg, parse_mode="HTML")
                    if sent_msg:
                        await self.fire_hedge_insight(user_id, user_id, "whale", {
                            "coin": sym,
                            "side": side_txt,
                            "val": val,
                            "px": px
                        }, reply_to_id=sent_msg.message_id)
                except:
                    pass


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
        """Fetch alerts and user settings from DB periodically."""
        while self.running:
            try:
                # Price Alerts
                alerts = await db.get_all_active_alerts()
                if alerts is not None:
                    self.active_alerts = alerts
                    
                # Whale Subscribers
                users = await db.get_all_users()
                self.whale_subscribers_cache = [u for u in users if u.get("whale_alerts")]
                
            except Exception as e:
                logger.error(f"Error refreshing alerts: {e}")
            await asyncio.sleep(10)

    def get_price(self, coin: str, original_id: str | None = None) -> float:
        if not coin:
            return 0.0
        if coin == "USDC":
            return 1.0
            
        # 1. Try original ID (e.g. "@156")
        if original_id and str(original_id) in self.mid_prices:
            return float(self.mid_prices[str(original_id)])

        # 2. Try coin name as is
        px = self.mid_prices.get(coin)
        if px is not None:
            return float(px)
            
        # 3. Handle U-prefix (internal name often has U)
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
        if not coin:
            return False
            
        # 1. Direct match (raw name from universe or ID)
        if coin in self.all_coins:
            return True
            
        # 2. Normalized match
        norm = self._resolve_coin_symbol(coin)
        if norm in self.all_coins:
            return True
            
        # 3. Handle resolved name or common names
        c_upper = str(coin).upper()
        if "/" in c_upper or c_upper in ("BTC", "ETH", "SOL", "HYPE", "USDC"):
            return True
            
        # 4. Check if it's a known resolved name from cache
        try:
            from bot.services import _SYMBOL_CACHE
            if coin in _SYMBOL_CACHE["spot"].values() or coin in _SYMBOL_CACHE["perp"].values():
                return True
        except:
            pass
            
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
        # WebData2 (Clearinghouse state) for Liquidation Monitor
        await self.ws.send(json.dumps({
            "method": "subscribe",
            "subscription": {"type": "webData2", "user": wallet}
        }))
        logger.info(f"Subscribed to updates (Fills, Orders, WebData2) for {wallet}")

    async def subscribe_all_mids(self):
        if not self.ws: return
        await self.ws.send(json.dumps({
            "method": "subscribe",
            "subscription": {"type": "allMids"}
        }))

    async def handle_message(self, data):
        # logger.debug(f"WS Message: {data}")
        channel = data.get("channel")
        msg_data = data.get("data", {})
        
        if channel == "allMids":
            await self.handle_mids(msg_data.get("mids", {}))
        elif channel == "userFills":
            await self.handle_fills(msg_data)
        elif channel == "openOrders":
            await self.handle_open_orders(msg_data)
        elif channel == "webData2":
            await self.handle_web_data2(msg_data)
        elif channel == "trades":
            await self.handle_trades(data)

    async def _listing_monitor_loop(self):
        """Periodically check for new assets in the universe."""
        while self.running:
            try:
                from bot.services import get_all_assets_meta
                meta = await get_all_assets_meta()
                
                current_assets = set()
                if meta["spot"]:
                    for u in meta["spot"].get("universe", []): current_assets.add(u["name"])
                if meta["perps"]:
                    for u in meta["perps"].get("universe", []): current_assets.add(u["name"])
                
                if not current_assets:
                    await asyncio.sleep(300)
                    continue

                known = await db.get_known_assets()
                if not known:
                    # First run, just save current
                    await db.update_known_assets(current_assets)
                else:
                    new_assets = current_assets - known
                    if new_assets:
                        logger.info(f"New assets detected: {new_assets}")
                        await self._broadcast_listing(new_assets)
                        await db.update_known_assets(current_assets)
                        # Refresh local universe for other logic
                        self.all_coins |= new_assets
                        
            except Exception as e:
                logger.error(f"Listing monitor error: {e}")
            await asyncio.sleep(600) # Check every 10 min

    async def _broadcast_listing(self, new_assets):
        users = await db.get_all_users()
        for sym in new_assets:
            for u in users:
                try:
                    lang = u.get("lang", "ru")
                    msg = _t(lang, "new_listing_msg", sym=sym)
                    sent_msg = await self.bot.send_message(u["user_id"], msg, parse_mode="HTML")
                    if sent_msg:
                        await self.fire_hedge_insight(u["user_id"], u["user_id"], "listings", {
                            "new_coin": sym
                        }, reply_to_id=sent_msg.message_id)
                    await asyncio.sleep(0.05)
                except: pass

    async def handle_mids(self, mids):
        for coin, price in mids.items():
            self.mid_prices[coin] = float(price)

        self.last_mids_update_ts = time.time()
        await self._update_market_history_and_alerts()
        await self.check_proximity()
        await self._check_custom_alerts() 
        
        # Periodically refresh asset context for Funding/OI alerts
        if time.time() - getattr(self, "_last_ctx_refresh", 0) > 60:
            asyncio.create_task(self._check_market_stats_alerts())
            self._last_ctx_refresh = time.time()

    async def _check_market_stats_alerts(self):
        """Check funding and OI alerts using metaAndAssetCtxs."""
        ctx = await get_perps_context()
        if not ctx or not isinstance(ctx, list) or len(ctx) != 2: return
        
        universe = ctx[0].get("universe", [])
        asset_ctxs = ctx[1]
        
        for alert in self.active_alerts:
            a_type = alert.get("type", "price")
            if a_type not in ("funding", "oi"): continue
            
            aid = str(alert["_id"])
            if aid in self.triggered_alerts: continue
            
            sym = alert["symbol"]
            target = alert.get("target")
            direction = alert["direction"]
            user_id = alert["user_id"]
            
            if target is None:
                continue
            
            # Find data
            idx = next((i for i, u in enumerate(universe) if u["name"] == sym), -1)
            if idx == -1 or idx >= len(asset_ctxs): continue
            
            data = asset_ctxs[idx]
            current_val = 0.0
            
            if a_type == "funding":
                current_val = float(data.get("funding", 0)) * 24 * 365 * 100 # APR
            else: # oi
                current_val = float(data.get("openInterest", 0)) * float(data.get("markPx", 1)) / 1e6 # $M
                
            triggered = (direction == "above" and current_val >= target) or \
                        (direction == "below" and current_val <= target)
            
            if triggered:
                self.triggered_alerts.add(aid)
                await db.delete_alert(aid)
                
                try:
                    lang = await db.get_lang(user_id)
                    unit = "% APR" if a_type == "funding" else "M$"
                    key = "funding_alert_msg" if a_type == "funding" else "oi_alert_msg"
                    
                    msg = _t(lang, key, 
                        sym=sym, 
                        current=f"{current_val:+.2f}", 
                        target=f"{target:+.2f}", 
                        direction=direction,
                        unit=unit
                    )
                    
                    from aiogram.utils.keyboard import InlineKeyboardBuilder
                    from aiogram.types import InlineKeyboardButton
                    kb = InlineKeyboardBuilder()
                    kb.row(InlineKeyboardButton(text=_t(lang, "btn_main_menu"), callback_data="cb_menu"))
                    
                    sent_msg = await self.bot.send_message(user_id, msg, reply_markup=kb.as_markup(), parse_mode="HTML")
                    if sent_msg:
                        await self.fire_hedge_insight(user_id, user_id, "funding" if a_type == "funding" else "oi", {
                            "coin": sym,
                            "val": current_val,
                            "target": target,
                            "type": a_type
                        }, reply_to_id=sent_msg.message_id)
                except: pass

    async def _check_custom_alerts(self):
        """Check all active custom alerts against current prices."""
        for alert in self.active_alerts:
            aid = str(alert.get("_id"))
            if aid in self.triggered_alerts:
                continue
                
            symbol = alert.get("symbol")
            target = alert.get("target")
            direction = alert.get("direction") # above / below
            user_id = alert.get("user_id")
            
            if target is None:
                continue
            
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
                success = await db.delete_alert(aid)
                logger.info(f"Price alert {aid} for {symbol} triggered and removed from DB: {success}")
                
                # Immediately remove from local memory to avoid stale data in case of race conditions
                self.active_alerts = [a for a in self.active_alerts if str(a.get("_id")) != aid]
                
                # Send message as background task to not block the loop
                asyncio.create_task(self._send_rich_alert(user_id, symbol, current_price, target, direction))

    async def _send_rich_alert(self, user_id: int, symbol: str, current_price: float, target: float, direction: str):
        try:
            lang = await db.get_lang(user_id)
        except:
            lang = "en"

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text=_t(lang, "btn_main_menu"), callback_data="cb_menu"))
        markup = kb.as_markup()

        # Build detailed text (Removed duplicate bell as it is in the locale)
        msg = f"<b>{_t(lang, 'custom_alert_title')}</b>\n\n"
        msg += f"<b>{symbol}</b> hit <b>${pretty_float(current_price)}</b>\n"
        msg += f"(Target: {direction} {pretty_float(target)})\n\n"
        
        # Add market context if available
        try:
            ctx, hlp_info = await asyncio.gather(
                get_perps_context(),
                get_hlp_info(),
                return_exceptions=True
            )
            
            if not isinstance(ctx, Exception) and ctx and isinstance(ctx, list) and len(ctx) == 2:
                universe = ctx[0].get("universe", [])
                asset_ctxs = ctx[1]
                
                # Find current asset data
                asset_data = None
                for i, u in enumerate(universe):
                    if u["name"] == symbol:
                        c = asset_ctxs[i]
                        funding = float(c.get("funding", 0)) * 24 * 365 * 100
                        vol = float(c.get("dayNtlVlm", 0))
                        change = ((float(c.get("markPx", 0)) - float(c.get("prevDayPx", 0))) / float(c.get("prevDayPx", 1))) * 100
                        asset_data = f"📊 <b>{symbol} Stats:</b>\n• 24h Change: <code>{change:+.2f}%</code>\n• Funding: <code>{funding:.1f}% APR</code>\n• 24h Vol: <b>${vol/1e6:.1f}M</b>"
                        break
                
                if asset_data:
                    msg += asset_data + "\n\n"

                # Generate 3 images
                if isinstance(hlp_info, Exception): hlp_info = None
                data_alpha = prepare_modern_market_data(asset_ctxs, universe, hlp_info)
                data_liq = prepare_liquidity_data(asset_ctxs, universe)
                
                buf_alpha = await render_html_to_image("market_stats.html", data_alpha)
                buf_liq = await render_html_to_image("liquidity_stats.html", data_liq)
                buf_heat = await render_html_to_image("funding_heatmap.html", data_alpha)
                
                media = [
                    InputMediaPhoto(media=BufferedInputFile(buf_heat.read(), filename="heatmap.png"), caption=msg, parse_mode="HTML"),
                    InputMediaPhoto(media=BufferedInputFile(buf_alpha.read(), filename="alpha.png")),
                    InputMediaPhoto(media=BufferedInputFile(buf_liq.read(), filename="liquidity.png"))
                ]
                await self.bot.send_media_group(user_id, media)
                # Send button after media group
                sent_msg = await self.bot.send_message(user_id, _t(lang, "btn_main_menu"), reply_markup=markup)
                if sent_msg:
                    await self.fire_hedge_insight(user_id, user_id, "volatility", {
                        "coin": symbol,
                        "price": current_price,
                        "triggered_alert": True
                    }, reply_to_id=sent_msg.message_id)
                return
        except Exception as e:
            logger.error(f"Error generating rich alert: {e}")

        # Fallback to plain text if image generation fails
        try:
            await self.bot.send_message(user_id, msg, reply_markup=markup, parse_mode="HTML")
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
                # Check user settings
                user_settings = await db.get_user_settings(chat_id)
                user_thresh = user_settings.get("watch_alert_pct")
                
                # If user defined a custom threshold, re-check logic
                effective_thresh = user_thresh if user_thresh is not None else thresh
                if abs(move) < effective_thresh:
                    continue

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

                msg = _t(lang, "watch_alert_title") + "\n" + _t(lang, "watch_alert_msg", dir_icon=direction, symbol=sym, move=f"{move*100:+.2f}", time=window//60, curr=f"{float(cur):.4f}", prev=f"{float(ref):.4f}")
                try:
                    sent_msg = await self.bot.send_message(chat_id, msg, parse_mode="HTML")
                    if sent_msg:
                        await self.fire_hedge_insight(chat_id, chat_id, "volatility", {
                            "coin": sym,
                            "move_pct": move*100,
                            "price": float(cur)
                        }, reply_to_id=sent_msg.message_id)
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
                current_px = self.get_price(coin, original_id=coin)
                
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
                # Use price difference for USD proximity
                price_dist = diff

                hit_pct = pct_diff <= pct_thresh if pct_thresh else False
                hit_usd = price_dist <= settings.PROXIMITY_USD_THRESHOLD if settings.PROXIMITY_USD_THRESHOLD else False

                # If the deviation is > 1.0%, we shouldn't trigger a proximity alert just because it's < $5 away (for high priced assets)
                if hit_usd and pct_diff > 0.01:
                    hit_usd = False

                if hit_pct or hit_usd:
                    oid = self._extract_order_id(order)
                    await self.trigger_proximity_alert(wallet, coin, limit_px, current_px, oid, side, sz, pct_diff, price_dist)

    async def trigger_proximity_alert(self, wallet, coin, limit_px, current_px, oid=None, side="", sz=0.0, pct_diff=0.0, price_dist=0.0):
        key = (wallet, coin, oid or "")
        last_alert = self.alert_cooldowns.get(key, 0)
        if time.time() - last_alert < settings.ALERT_COOLDOWN:
            return
        self.alert_cooldowns[key] = time.time()
        
        users = await db.get_users_by_wallet(wallet)
        for user in users:
            chat_id = user.get('chat_id')
            lang = "ru"
            
            # Check for user overrides
            user_settings = await db.get_user_settings(chat_id)
            user_prox_pct = user_settings.get("prox_alert_pct")
            
            # If user has custom pct setting, check if we actually hit it
            # Because check_proximity uses global settings to trigger this function
            # We must re-verify for this specific user
            eff_thresh = user_prox_pct if user_prox_pct is not None else settings.PROXIMITY_THRESHOLD
            if side == "buy" and not user_prox_pct: eff_thresh = settings.BUY_PROXIMITY_THRESHOLD
            elif side == "sell" and not user_prox_pct: eff_thresh = settings.SELL_PROXIMITY_THRESHOLD
            
            if pct_diff > eff_thresh and (price_dist > settings.PROXIMITY_USD_THRESHOLD):
                # If both failed (pct too high AND usd too high), skip
                continue

            try:
                if chat_id:
                    lang = await db.get_lang(chat_id)
            except Exception:
                lang = "ru"

            is_spot = str(coin).startswith("@")
            safe_coin = html.escape(await get_symbol_name(coin, is_spot=is_spot))
            
            if side == "buy":
                side_txt = _t(lang, "prox_alert_buy")
                dir_txt = "↓"
            elif side == "sell":
                side_txt = _t(lang, "prox_alert_sell")
                dir_txt = "↑"
            else:
                side_txt = _t(lang, "prox_alert_order")
                dir_txt = ""

            # Check for "dust" orders triggering USD alert while being far away
            if pct_diff > 0.10:
                continue

            # Formatted Numbers
            mid_fmt = pretty_float(current_px)
            lim_fmt = pretty_float(limit_px)
            fill_pct_fmt = f"{dir_txt} {(abs(current_px - limit_px) / current_px) * 100:.2f}%"
            diff_pct_fmt = f"{pct_diff*100:.2f}% (thr {eff_thresh*100:.2f}%)"
            
            msg = _t(lang, "prox_alert_title") + "\n"
            msg += f"{side_txt} {safe_coin}\n"
            msg += f"{_t(lang, 'prox_alert_mid')}: <b>{mid_fmt}</b>\n"
            msg += f"{_t(lang, 'prox_alert_limit')}: <b>{lim_fmt}</b>\n"
            msg += f"{_t(lang, 'prox_alert_to_fill')}: {fill_pct_fmt}\n"
            msg += f"{_t(lang, 'prox_alert_diff')}: {diff_pct_fmt}\n"
            
            msg += f"{_t(lang, 'prox_alert_dist')}: <b>${price_dist:.2f}</b> (thr ${settings.PROXIMITY_USD_THRESHOLD:.2f})\n"
                
            msg += f"Wallet: <code>{wallet[:6]}...{wallet[-4:]}</code>"
            try:
                sent_msg = await self.bot.send_message(chat_id, msg, parse_mode="HTML")
                if sent_msg:
                    await self.fire_hedge_insight(chat_id, chat_id, "proximity", {
                        "coin": safe_coin,
                        "side": side,
                        "limit_px": limit_px,
                        "current_px": current_px,
                        "dist_usd": price_dist
                    }, reply_to_id=sent_msg.message_id)
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
                px = float(fill.get("px") or 0)
                sz = float(fill.get("sz") or 0)
                
                logger.info(f"Processing fill: {coin} {side} {sz} @ {px} for {user_wallet}")
                
                if not all([coin, side, px, sz]):
                    logger.warning(f"Skipping incomplete fill: {fill}")
                    continue
                
                usd_value = px * sz
                fee = float(fill.get("fee", 0))
                closed_pnl = float(fill.get("closedPnl", 0))
                
                # Resolve symbol name safely (async)
                is_spot_guess = str(coin).startswith("@") or (isinstance(coin, str) and "/" in coin)
                sym_name = await get_symbol_name(coin, is_spot=is_spot_guess)
                
                logger.info(f"Resolved sym_name: {sym_name} (is_spot_guess: {is_spot_guess})")
                
                # Fix: Check the original coin ID instead of resolved name
                if not self._is_known_coin(coin):
                    logger.warning(f"Skipping unknown coin: {sym_name} (original: {coin})")
                    continue
                
                fill_with_user = dict(fill)
                fill_with_user["user"] = user_wallet
                await db.save_fill(fill_with_user)
                
                # Check for liquidation
                is_liq = fill.get("liquidation", False) or fill.get("isLiquidation", False)
                
                # Check user settings (threshold)
                threshold = user.get("threshold", 0.0)
                if usd_value < threshold and not is_liq:
                    logger.info(f"Fill value ${usd_value:.2f} below threshold ${threshold:.2f}, skipping alert")
                    continue

                side_emoji = "🟢" if side.lower() in ("b","buy","bid") else "🔴"
                if is_liq:
                    side_emoji = "💀"
                
                safe_coin = html.escape(sym_name)
                tag = user.get("tag")
                wallet_display = f"<b>{html.escape(tag)}</b>" if tag else f"<code>{user_wallet[:6]}...{user_wallet[-4:]}</code>"
                
                if is_liq:
                    title = _t(lang, "fill_alert_liq")
                else:
                    title = _t(lang, "fill_alert_title")

                # Get current price for comparison  
                current_px = self.get_price(coin, original_id=coin)
                
                # Build extended message
                msg = f"{side_emoji} {title}\n\n"
                msg += f"<b>{side.upper()} {sz} {safe_coin}</b> @ ${pretty_float(px)}\n"
                msg += f"💰 {_t(lang, 'value_lbl')}: <b>${pretty_float(usd_value, 2)}</b>\n"
                
                # Show current price comparison
                if current_px and current_px != px:
                    price_change = ((current_px - px) / px) * 100
                    change_icon = "📈" if price_change > 0 else "📉"
                    msg += f"📊 Now: <b>${pretty_float(current_px)}</b> ({change_icon} {price_change:+.2f}%)\n"
                
                if fee != 0:
                    msg += f"💸 Fee: <code>${pretty_float(fee, 2)}</code>\n"
                
                if closed_pnl != 0:
                    pnl_icon = "📈" if closed_pnl > 0 else "📉"
                    msg += f"{pnl_icon} <b>Realized PnL: {'+' if closed_pnl > 0 else ''}${pretty_float(closed_pnl, 2)}</b>\n"

                # Add timestamp
                fill_time = fill.get("time")
                if fill_time:
                    try:
                        from datetime import datetime
                        ts = datetime.fromtimestamp(int(fill_time) / 1000)
                        msg += f"🕐 {ts.strftime('%H:%M:%S')}\n"
                    except:
                        pass

                msg += f"\n👛 Wallet: {wallet_display}"
                
                # Build inline keyboard with quick actions
                from aiogram.utils.keyboard import InlineKeyboardBuilder
                from aiogram.types import InlineKeyboardButton
                kb = InlineKeyboardBuilder()
                kb.row(
                    InlineKeyboardButton(text="📊 Positions", callback_data="cb_positions"),
                    InlineKeyboardButton(text=f"🔔 Alert {sym_name[:6]}", callback_data=f"quick_alert:{sym_name}")
                )
                kb.row(InlineKeyboardButton(text="🏠 Menu", callback_data="cb_menu"))
                
                try:
                    sent_msg = await self.bot.send_message(chat_id, msg, reply_markup=kb.as_markup(), parse_mode="HTML")
                    # Fire Hedge Insight
                    if sent_msg:
                        await self.fire_hedge_insight(chat_id, chat_id, "liquidation" if is_liq else "fills", {
                            "coin": sym_name,
                            "side": side,
                            "sz": sz,
                            "px": px,
                            "val": usd_value,
                            "pnl": closed_pnl,
                            "is_liq": is_liq
                        }, reply_to_id=sent_msg.message_id)
                except Exception as e:
                    logger.error(f"Failed to send fill notification to {chat_id}: {e}")

    async def handle_open_orders(self, data):
        orders = []
        if isinstance(data, list):
            orders = data
        elif isinstance(data, dict):
             orders = data.get("orders", [])
             
        user_wallet = data.get("user") if isinstance(data, dict) else None
        if not user_wallet:
            return

        user_wallet = user_wallet.lower()
        
        # Detect NEW orders for placement alerts
        old_orders = self.open_orders.get(user_wallet, [])
        old_oids = {self._extract_order_id(o) for o in old_orders}
        
        new_orders_to_alert = []
        for o in orders:
            oid = self._extract_order_id(o)
            if oid and oid not in old_oids:
                new_orders_to_alert.append(o)

        if self.all_coins:
            filtered = []
            for o in orders:
                coin, _ = self._extract_order_fields(o)
                if self._is_known_coin(coin):
                    filtered.append(o)
            self.open_orders[user_wallet] = filtered
        else:
            self.open_orders[user_wallet] = orders

        # Send alerts for new orders
        if new_orders_to_alert:
            users = await db.get_users_by_wallet(user_wallet)
            for user in users:
                chat_id = user.get("chat_id")
                lang = "ru"
                try:
                    lang = await db.get_lang(chat_id)
                except:
                    pass
                
                for o in new_orders_to_alert:
                    coin_raw, px = self._extract_order_fields(o)
                    if not self._is_known_coin(coin_raw):
                        continue
                    
                    is_spot = str(coin_raw).startswith("@")
                    coin = await get_symbol_name(coin_raw, is_spot=is_spot)
                        
                    sz = self._extract_order_size(o)
                    side = self._extract_order_side(o)
                    side_icon = "🟢" if side == "buy" else "🔴"
                    
                    tag = user.get("tag")
                    wallet_display = f"<b>{html.escape(tag)}</b>" if tag else f"<code>{user_wallet[:6]}...{user_wallet[-4:]}</code>"
                    
                    msg = f"🆕 <b>{_t(lang, 'order_placed_title')}</b>\n"
                    msg += f"{side_icon} {side.upper()} {sz} <b>{coin}</b> @ ${pretty_float(px)}\n"
                    msg += f"Wallet: {wallet_display}"
                    
                    try:
                        sent_msg = await self.bot.send_message(chat_id, msg, parse_mode="HTML")
                        if sent_msg:
                            await self.fire_hedge_insight(chat_id, chat_id, "proximity", {
                                "coin": coin,
                                "side": side,
                                "px": px,
                                "is_new_order": True
                            }, reply_to_id=sent_msg.message_id)
                    except Exception as e:
                        logger.error(f"Failed to send order alert: {e}")
    
    async def handle_web_data2(self, data):
        """Handle clearinghouse state updates (margin/risk)."""
        # We need 'user' to be present to know who to alert
        user_wallet = data.get("user") # Try to get it from root of data
        # Sometimes it's not there.
        # If we can't identify the user, we skip.
        if not user_wallet:
            # Some reverse engineering or hope?
            # For now, safe fail.
            return
            
        user_wallet = user_wallet.lower()
        
        clearinghouse_state = data.get("clearinghouseState", {})
        margin_summary = clearinghouse_state.get("marginSummary", {})
        
        account_value = float(margin_summary.get("accountValue", 0) or 0)
        total_margin_used = float(margin_summary.get("totalMarginUsed", 0) or 0)
        
        if account_value <= 0: return
        
        margin_ratio = total_margin_used / account_value
        
        # ALERT
        if margin_ratio > 0.8:
            # Check cooldown
            last_alert = self.liq_alert_cooldowns.get(user_wallet, 0)
            if time.time() - last_alert < 3600: # 1 hour
                return
            
            self.liq_alert_cooldowns[user_wallet] = time.time()
            
            # Notify
            users = await db.get_users_by_wallet(user_wallet)
            for user in users:
                chat_id = user.get('chat_id')
                lang = "ru"
                try:
                    lang = await db.get_lang(chat_id)
                except:
                    lang = "ru"
                    
                msg = _t(lang, "liq_risk_title") + "\n" + _t(lang, "liq_risk_msg", 
                    wallet=f"{user_wallet[:6]}...", 
                    ratio=f"{margin_ratio*100:.1f}", 
                    equity=pretty_float(account_value)
                )

                try:
                    sent_msg = await self.bot.send_message(chat_id, msg, parse_mode="HTML")
                    if sent_msg:
                        await self.fire_hedge_insight(chat_id, chat_id, "margin", {
                            "margin_ratio": margin_ratio,
                            "equity": account_value,
                            "wallet": user_wallet
                        }, reply_to_id=sent_msg.message_id)
                except:
                    pass

    async def _ledger_loop(self):
        """Monitor deposits and withdrawals via REST polling."""
        from bot.services import get_user_ledger
        logger.info("Starting Ledger Monitor Loop")
        
        while self.running:
            try:
                # 1. Get unique wallets
                wallets = await db.get_all_watched_addresses()
                
                for wallet in wallets:
                    # 2. Get state
                    w_state = await db.get_wallet_state(wallet)
                    last_time = int(w_state.get("last_ledger_time", 0)) if w_state else 0
                    
                    # 3. Fetch updates
                    # If last_time == 0, we fetch updates, find max time, save it, and continue (no alert on first run)
                    updates = await get_user_ledger(wallet, start_time=last_time + 1 if last_time > 0 else None)
                    
                    if not updates or not isinstance(updates, list):
                        continue
                        
                    # Filter updates
                    new_max_time = last_time
                    valid_updates = []
                    
                    for event in updates:
                        # event structure: {"hash": "...", "time": 123456789, "delta": {...}}
                        ts = int(event.get("time", 0))
                        if ts > last_time:
                            valid_updates.append(event)
                            if ts > new_max_time:
                                new_max_time = ts
                    
                    # Initialization check
                    if last_time == 0:
                        if new_max_time > 0:
                            await db.update_wallet_ledger_time(wallet, new_max_time)
                        continue
                    
                    # Process Alerts
                    valid_updates.sort(key=lambda x: int(x.get("time", 0)))
                    
                    for event in valid_updates:
                        delta = event.get("delta", {})
                        type_ = delta.get("type")
                        
                        # Supported types
                        if type_ not in ("deposit", "withdraw", "transfer", "spotTransfer"):
                            continue
                            
                        # Extract amount
                        amount = delta.get("usdc") or delta.get("amount") or 0.0
                        try:
                            amount = float(amount)
                        except:
                            amount = 0.0
                        
                        # Determine Alert Key
                        key_map = {
                            "deposit": "deposit_alert",
                            "withdraw": "withdraw_alert",
                            "transfer": "transfer_alert",
                            "spotTransfer": "transfer_alert"
                        }
                        
                        key = key_map.get(type_, "transfer_alert")
                        
                        # Notify Users
                        users = await db.get_users_by_wallet(wallet)
                        for user in users:
                            chat_id = user["chat_id"]
                            lang = await db.get_lang(chat_id)
                            
                            title = _t(lang, key)
                            msg = f"{title}\n"
                            msg += f"👛 <code>{wallet[:6]}...{wallet[-4:]}</code>\n"
                            msg += _t(lang, "ledger_amt", amount=pretty_float(amount))
                            
                            # Add time
                            try:
                                from datetime import datetime
                                ts_dt = datetime.fromtimestamp(int(event.get("time", 0)) / 1000)
                                msg += f"\n🕐 {ts_dt.strftime('%H:%M:%S')}"
                            except: pass

                            try:
                                sent_msg = await self.bot.send_message(chat_id, msg, parse_mode="HTML")
                                if sent_msg:
                                    await self.fire_hedge_insight(chat_id, chat_id, "ledger", {
                                        "type": type_,
                                        "amount": amount,
                                        "wallet": wallet
                                    }, reply_to_id=sent_msg.message_id)
                            except: pass
                            
                    # Update DB
                    if new_max_time > last_time:
                        await db.update_wallet_ledger_time(wallet, new_max_time)
                        
                    await asyncio.sleep(0.5) # Pace per wallet
                    
                await asyncio.sleep(60) # Global loop interval
                
            except Exception as e:
                logger.error(f"Ledger Loop Error: {e}")
                await asyncio.sleep(60)
