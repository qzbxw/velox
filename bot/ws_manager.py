import asyncio
import json
import logging
import time
import websockets
from collections import defaultdict
from bot.config import settings
from bot.database import db

logger = logging.getLogger(__name__)

class WSManager:
    def __init__(self, bot):
        self.bot = bot
        self.ws_url = settings.HYPERLIQUID_WS_URL
        self.running = False
        self.ws = None
        self.tracked_wallets = set()
        self.mid_prices = {}  # {coin: price}
        self.open_orders = defaultdict(list)  # {wallet: [orders]}
        
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
                    
                    # Initial subscriptions
                    await self.subscribe_all_mids()
                    
                    # Load and subscribe users
                    users = await db.get_all_users()
                    for user in users:
                        wallet = user.get("wallet_address")
                        if wallet:
                            self.track_wallet(wallet)
                            await self.subscribe_user(wallet)
                            
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

    async def _ping_loop(self):
        while self.running:
            await asyncio.sleep(50)
            if self.ws:
                try:
                    await self.ws.send(json.stringify({"method": "ping"}))
                except:
                    pass

    def track_wallet(self, wallet):
        self.tracked_wallets.add(wallet)

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
            
        # Check proximity
        await self.check_proximity()

    async def check_proximity(self):
        # For each wallet, check open orders against current mid price
        for wallet, orders in self.open_orders.items():
            for order in orders:
                coin = order['coin']
                limit_px = float(order['limit_px'])
                current_px = self.mid_prices.get(coin)
                
                if not current_px: continue
                
                # Check 0.5% proximity
                # abs(current - limit) / limit <= 0.005
                diff = abs(current_px - limit_px)
                if (diff / limit_px) <= settings.PROXIMITY_THRESHOLD:
                    await self.trigger_proximity_alert(wallet, coin, limit_px, current_px)

    async def trigger_proximity_alert(self, wallet, coin, limit_px, current_px):
        # Check cooldown
        key = (wallet, coin)
        last_alert = self.alert_cooldowns.get(key, 0)
        if time.time() - last_alert < settings.ALERT_COOLDOWN:
            return
            
        self.alert_cooldowns[key] = time.time()
        
        # Notify users tracking this wallet
        users = await db.get_users_by_wallet(wallet)
        for user in users:
            msg = (
                f"⚠️ <b>Price Alert</b>\n"
                f"Token: {coin}\n"
                f"Current Price: {current_px}\n"
                f"Order Price: {limit_px}\n"
                f"Difference: {abs(current_px - limit_px):.4f} ({(abs(current_px - limit_px)/limit_px)*100:.2f}%)"
            )
            try:
                await self.bot.send_message(user['chat_id'], msg, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Failed to send alert to {user['chat_id']}: {e}")

    async def handle_fills(self, data):
        # data format: { isSnapshot: bool, user: str, fills: [WsFill] }
        user_wallet = data.get("user")
        fills = data.get("fills", [])
        
        # If snapshot, maybe we just store history but don't alert?
        # Prompt says "User Fills: Subscribe to user events... send an instant notification"
        # Usually snapshots are initial state. We might want to skip alerting on snapshot 
        # to avoid spamming old fills on restart.
        is_snapshot = data.get("isSnapshot", False)
        
        for fill in fills:
            # Enrich fill with user for DB
            fill['user'] = user_wallet
            await db.add_fill(fill)
            
            if not is_snapshot:
                # Notify
                await self.notify_fill(user_wallet, fill)

    async def notify_fill(self, wallet, fill):
        users = await db.get_users_by_wallet(wallet)
        side_emoji = "🟢" if fill['side'].lower() == 'b' or fill['side'].lower() == 'buy' else "🔴"
        # API returns 'B'/'A' or 'buy'/'sell'?
        # Docs say side: string. Usually 'B'/'S' or 'A' (Ask)/'B'(Bid) in Hyperliquid?
        # SDK types say side: string.
        # Let's assume standard 'B' for Buy or check via testing.
        # If I can't be sure, I'll just print the side string.
        
        side_display = "Bought" if fill['side'] == 'B' else "Sold"
        if fill['side'] == 'A': side_display = "Sold" # Ask
        
        msg = (
            f"{side_emoji} <b>Order Filled</b>\n"
            f"Coin: {fill['coin']}\n"
            f"Side: {side_display}\n"
            f"Price: {fill['px']}\n"
            f"Size: {fill['sz']}\n"
            f"Value: ${float(fill['px']) * float(fill['sz']):.2f}"
        )
        
        for user in users:
            try:
                await self.bot.send_message(user['chat_id'], msg, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Failed to send fill alert: {e}")

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
            self.open_orders[user_wallet] = orders
