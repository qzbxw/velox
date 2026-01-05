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
        
    # --- ALERTS ---
    async def add_price_alert(self, user_id: int, symbol: str, price: float, direction: str):
        """
        direction: 'above' or 'below'
        """
        await self.alerts.insert_one({
            "user_id": user_id,
            "symbol": symbol.upper(),
            "price": price,
            "direction": direction,
            "created_at": time.time()
        })
        
    async def get_user_alerts(self, user_id: int):
        cursor = self.alerts.find({"user_id": user_id})
        return await cursor.to_list(length=None)
        
    async def get_all_active_alerts(self):
        cursor = self.alerts.find({})
        return await cursor.to_list(length=None)
        
    async def delete_alert(self, alert_id: str):
        try:
            await self.alerts.delete_one({"_id": ObjectId(alert_id)})
        except:
            pass

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

db = Database(settings.MONGO_URI, settings.MONGO_DB_NAME)