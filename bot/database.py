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
                "added_at": time.time()
            })

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
        # We need to find users who have this wallet in their wallets collection
        # OR users who have it as their primary wallet (legacy)
        
        # 1. Get users from 'wallets' collection
        cursor = self.wallets.find({"address": wallet_address.lower()})
        wallet_docs = await cursor.to_list(length=None)
        user_ids = {doc["user_id"] for doc in wallet_docs}
        
        # 2. Get users from 'users' collection (legacy wallet_address field)
        cursor_legacy = self.users.find({"wallet_address": wallet_address.lower()})
        legacy_docs = await cursor_legacy.to_list(length=None)
        for doc in legacy_docs:
            user_ids.add(doc["user_id"])
            
        # Return partial user objects (at least chat_id)
        # We can just return the user_ids wrapped in dicts to match expected interface
        # or fetch full user docs. WSManager expects objects with 'chat_id'.
        return [{"chat_id": uid} for uid in user_ids]

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

db = Database(settings.MONGO_URI, settings.MONGO_DB_NAME)