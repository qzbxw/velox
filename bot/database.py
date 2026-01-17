import motor.motor_asyncio
import time
from bson import ObjectId
from bot.config import settings

class Database:
    def __init__(self, uri, db_name):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self.client[db_name]
        self.users = self.db.users
        self.wallets = self.db.wallets
        self.fills = self.db.fills
        self.watchlist = self.db.watchlist
        self.alerts = self.db.alerts  # New collection for price alerts
        self.wallet_states = self.db.wallet_states  # Tracks last update times

    async def init_db(self):
        """Initialize database indexes for performance and integrity."""
        # Unique index for fills to avoid duplicates
        await self.fills.create_index([("oid", 1)], unique=True)
        # Indexes for frequent lookups
        await self.wallets.create_index([("address", 1)])
        await self.wallets.create_index([("user_id", 1)])
        await self.users.create_index([("user_id", 1)], unique=True)
        await self.alerts.create_index([("user_id", 1)])
        await self.alerts.create_index([("symbol", 1)])

    async def add_user(self, user_id, wallet_address=None):
        existing = await self.users.find_one({"user_id": user_id})
        if not existing:
            await self.users.insert_one({
                "user_id": user_id,
                "wallet_address": wallet_address,  # Primary/Legacy wallet
                "joined_at": time.time(),
                "lang": "en"
            })

    async def add_wallet(self, user_id, wallet_address):
        """Add a wallet to the separate wallets collection."""
        wallet = wallet_address.lower()
        existing = await self.wallets.find_one({"user_id": user_id, "address": wallet})
        if not existing:
            await self.wallets.insert_one({
                "user_id": user_id,
                "address": wallet,
                "added_at": time.time(),
                "tag": None,
                "threshold": 0.0  # Min USD value for notifications
            })

    async def update_wallet_settings(self, user_id, wallet_address, tag=None, threshold=None):
        update_data = {}
        if tag is not None: update_data["tag"] = tag
        if threshold is not None: update_data["threshold"] = float(threshold)
        
        if update_data:
            await self.wallets.update_one(
                {"user_id": user_id, "address": wallet_address.lower()},
                {"$set": update_data}
            )

    async def list_wallets_full(self, user_id):
        cursor = self.wallets.find({"user_id": user_id})
        return await cursor.to_list(length=None)

    async def list_wallets(self, user_id):
        cursor = self.wallets.find({"user_id": user_id})
        wallets = []
        async for doc in cursor:
            wallets.append(doc["address"])
        return wallets

    async def remove_wallet(self, user_id, wallet_address):
        await self.wallets.delete_one({"user_id": user_id, "address": wallet_address.lower()})

    async def set_lang(self, user_id, lang):
        await self.users.update_one(
            {"user_id": user_id},
            {"$set": {"lang": lang}},
            upsert=True
        )

    async def get_lang(self, user_id):
        u = await self.users.find_one({"user_id": user_id})
        return u.get("lang", "en") if u else "en"

    async def get_all_users(self):
        cursor = self.users.find({})
        return await cursor.to_list(length=None)

    async def get_users_by_wallet(self, wallet_address):
        """Returns list of user configs for this wallet, including tags and thresholds."""
        cursor = self.wallets.find({"address": wallet_address.lower()})
        wallet_docs = await cursor.to_list(length=None)
        
        results = []
        for doc in wallet_docs:
            results.append({
                "chat_id": doc["user_id"],
                "tag": doc.get("tag"),
                "threshold": doc.get("threshold", 0.0)
            })
            
        # Legacy check
        cursor_legacy = self.users.find({"wallet_address": wallet_address.lower()})
        legacy_docs = await cursor_legacy.to_list(length=None)
        for doc in legacy_docs:
            # Only add if not already added from wallets collection
            if not any(r["chat_id"] == doc["user_id"] for r in results):
                results.append({
                    "chat_id": doc["user_id"],
                    "tag": None,
                    "threshold": 0.0
                })
            
        return results

    # --- WATCHLIST ---
    async def get_watchlist(self, user_id):
        doc = await self.watchlist.find_one({"user_id": user_id})
        return doc.get("symbols", []) if doc else []

    async def add_watch_symbol(self, user_id, symbol):
        await self.watchlist.update_one(
            {"user_id": user_id},
            {"$addToSet": {"symbols": symbol.upper()}},
            upsert=True
        )

    async def remove_watch_symbol(self, user_id, symbol):
        await self.watchlist.update_one(
            {"user_id": user_id},
            {"$pull": {"symbols": symbol.upper()}}
        )

    # --- FILLS (PnL) ---
    async def save_fill(self, fill_data):
        # Unique index on (coin, oid) is recommended in Mongo setup
        await self.fills.update_one(
            {"oid": fill_data["oid"]},
            {"$set": fill_data},
            upsert=True
        )

    async def get_fills_range(self, wallet, start_ts, end_ts):
        cursor = self.fills.find({
            "user": wallet.lower(),
            "time": {"$gte": start_ts * 1000, "$lt": end_ts * 1000}
        })
        return await cursor.to_list(length=None)

    async def get_fills_before(self, wallet, ts):
        cursor = self.fills.find({
            "user": wallet.lower(),
            "time": {"$lt": ts * 1000}
        })
        return await cursor.to_list(length=None)

    async def get_fills_by_coin(self, wallet, coin):
        cursor = self.fills.find({
            "user": wallet.lower(), 
            "coin": coin
        })
        return await cursor.to_list(length=None)

    async def get_fills(self, wallet, start_ts, end_ts):
        return await self.get_fills_range(wallet, start_ts, end_ts)
        
    # --- ALERTS ---
    async def add_alert(self, user_id: int, symbol: str, target: float, direction: str, alert_type: str = "price"):
        """
        alert_type: 'price', 'funding', 'oi'
        direction: 'above', 'below'
        """
        await self.alerts.insert_one({
            "user_id": user_id,
            "symbol": symbol.upper(),
            "target": target,
            "direction": direction,
            "type": alert_type,
            "created_at": time.time()
        })

    async def add_price_alert(self, user_id, symbol, price, direction):
        return await self.add_alert(user_id, symbol, price, direction, "price")

    async def get_known_assets(self):
        doc = await self.db.internal_state.find_one({"key": "known_assets"})
        return set(doc.get("list", [])) if doc else set()

    async def update_known_assets(self, assets_list):
        await self.db.internal_state.update_one(
            {"key": "known_assets"},
            {"$set": {"list": list(assets_list)}},
            upsert=True
        )

    async def get_user_alerts(self, user_id: int):
        cursor = self.alerts.find({"user_id": user_id})
        return await cursor.to_list(length=None)
        
    async def get_all_active_alerts(self):
        cursor = self.alerts.find({})
        return await cursor.to_list(length=None)
        
    async def delete_alert(self, alert_id: str):
        try:
            if not alert_id: return False
            oid = ObjectId(alert_id) if isinstance(alert_id, str) else alert_id
            res = await self.alerts.delete_one({"_id": oid})
            return res.deleted_count > 0
        except Exception as e:
            # You can add logging here if needed
            return False

    async def delete_all_user_alerts(self, user_id: int):
        await self.alerts.delete_many({"user_id": user_id})

    # --- USER SETTINGS ---
    async def update_user_settings(self, user_id, settings_dict):
        """
        settings_dict can include:
        - whale_alerts (bool)
        - whale_threshold (float)
        - prox_alert_pct (float)
        """
        await self.users.update_one(
            {"user_id": user_id},
            {"$set": settings_dict},
            upsert=True
        )

    async def get_user_settings(self, user_id):
        user = await self.users.find_one({"user_id": user_id})
        return user if user else {}

    async def get_overview_settings(self, user_id: int) -> dict:
        """
        Get Market Overview settings for a user.
        Returns dict with defaults if not found.
        """
        user = await self.users.find_one({"user_id": user_id})
        if not user:
            return {
                "schedules": ["06:00", "18:00"], # Default Morning & Evening
                "style": "detailed",
                "prompt_override": None,
                "enabled": True
            }
        
        return user.get("overview", {
            "schedules": ["06:00", "18:00"],
            "style": "detailed",
            "prompt_override": None,
            "enabled": True
        })

    async def update_overview_settings(self, user_id: int, settings: dict):
        """
        Update Market Overview settings.
        settings: dict containing any of keys: schedules, style, prompt_override, enabled
        """
        # First ensure user exists using upsert via update_one
        await self.users.update_one(
            {"user_id": user_id},
            {"$set": {
                f"overview.{k}": v for k, v in settings.items()
            }},
            upsert=True
        )

    # --- HEDGE SETTINGS ---
    async def get_hedge_settings(self, user_id: int) -> dict:
        user = await self.users.find_one({"user_id": user_id})
        default = {
            "enabled": False,
            "triggers": {
                "liquidation": True,
                "fills": True,
                "proximity": True,
                "volatility": True,
                "whale": False,
                "margin": True,
                "listings": True,
                "ledger": True,
                "funding": True
            }
        }
        if not user:
            return default
        return user.get("hedge", default)

    async def update_hedge_settings(self, user_id: int, settings: dict):
        # We use a similar flat update strategy as overview
        update_doc = {}
        if "enabled" in settings:
            update_doc["hedge.enabled"] = settings["enabled"]
        if "triggers" in settings:
            for k, v in settings["triggers"].items():
                update_doc[f"hedge.triggers.{k}"] = v
        
        await self.users.update_one(
            {"user_id": user_id},
            {"$set": update_doc},
            upsert=True
        )

    # --- WALLET STATES (Ledger Tracking) ---
    async def get_all_watched_addresses(self):
        """Get list of unique wallet addresses currently being watched."""
        return await self.wallets.distinct("address")

    async def get_wallet_state(self, address):
        return await self.wallet_states.find_one({"address": address.lower()})

    async def update_wallet_ledger_time(self, address, timestamp):
        await self.wallet_states.update_one(
            {"address": address.lower()},
            {"$set": {"last_ledger_time": int(timestamp)}},
            upsert=True
        )

db = Database(settings.MONGO_URI, settings.MONGO_DB_NAME)