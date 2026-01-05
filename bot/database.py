import motor.motor_asyncio
import time
from bot.config import settings
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGO_URI)
        self.db = self.client[settings.MONGO_DB_NAME]
        self.users = self.db.users
        self.fills = self.db.fills

    async def add_user(self, chat_id: int, wallet_address: str):
        """Upsert user with wallet address."""
        await self.users.update_one(
            {"chat_id": chat_id},
            {
                "$set": {
                    "user_id": chat_id,
                    "updated_at": time.time()
                },
                "$setOnInsert": {
                    "created_at": time.time(),
                    "watchlist": ["BTC", "ETH"],
                    "lang": "ru",
                }
            },
            upsert=True
        )
        logger.info(f"User {chat_id} updated with wallet {wallet_address}")

    async def get_user(self, chat_id: int):
        return await self.users.find_one({"chat_id": chat_id})

    async def add_wallet(self, chat_id: int, wallet_address: str):
        """Add a wallet to the user's wallets list (no duplicates)."""
        if not wallet_address or not wallet_address.startswith("0x") or len(wallet_address) != 42:
            raise ValueError("Invalid address")
        await self.users.update_one(
            {"chat_id": chat_id},
            {
                "$addToSet": {"wallets": wallet_address},
                "$set": {"updated_at": time.time()},
                "$setOnInsert": {
                    "created_at": time.time(),
                    "watchlist": ["BTC", "ETH"],
                    "lang": "ru",
                }
            },
            upsert=True,
        )
        logger.info(f"Added wallet {wallet_address} to user {chat_id}")

    async def remove_wallet(self, chat_id: int, wallet_address: str):
        """Remove a wallet from the user's wallets list."""
        await self.users.update_one(
            {"chat_id": chat_id},
            {"$pull": {"wallets": wallet_address}, "$set": {"updated_at": time.time()}},
        )
        logger.info(f"Removed wallet {wallet_address} from user {chat_id}")

    async def list_wallets(self, chat_id: int):
        """Return list of wallets for the user."""
        user = await self.get_user(chat_id)
        if not user:
            return []
        # Migrate legacy wallet_address if present and wallets list empty
        if isinstance(user.get("wallet_address"), str) and not user.get("wallets"):
            await self.users.update_one(
                {"chat_id": chat_id},
                {"$set": {"wallets": [user["wallet_address"]]}, "$unset": {"wallet_address": ""}},
            )
            return [user["wallet_address"]]
        return [w for w in user.get("wallets", []) if isinstance(w, str)]

    async def set_lang(self, chat_id: int, lang: str):
        l = (lang or "").lower()
        if l not in ("ru", "en"):
            return
        await self.users.update_one(
            {"chat_id": chat_id},
            {"$set": {"lang": l, "updated_at": time.time()}},
            upsert=True,
        )

    async def get_lang(self, chat_id: int) -> str:
        user = await self.get_user(chat_id)
        if isinstance(user, dict):
            l = user.get("lang")
            if isinstance(l, str) and l.lower() in ("ru", "en"):
                return l.lower()
        return "ru"

    async def add_watch_symbol(self, chat_id: int, symbol: str):
        sym = (symbol or "").upper()
        if not sym:
            return
        await self.users.update_one(
            {"chat_id": chat_id},
            {"$addToSet": {"watchlist": sym}, "$set": {"updated_at": time.time()}},
            upsert=True,
        )

    async def remove_watch_symbol(self, chat_id: int, symbol: str):
        sym = (symbol or "").upper()
        if not sym:
            return
        await self.users.update_one(
            {"chat_id": chat_id},
            {"$pull": {"watchlist": sym}, "$set": {"updated_at": time.time()}},
        )

    async def get_watchlist(self, chat_id: int):
        user = await self.get_user(chat_id)
        wl = []
        if isinstance(user, dict) and isinstance(user.get("watchlist"), list):
            wl = [str(x).upper() for x in user["watchlist"] if x]
        return wl

    async def get_all_users(self):
        """Return list of all users."""
        users = []
        async for user in self.users.find():
            users.append(user)
        return users

    async def get_users_by_wallet(self, wallet_address: str):
        """Return list of users tracking a specific wallet."""
        # Although we assume 1:1 mostly, multiple users could track same wallet
        users = []
        async for user in self.users.find({"wallet_address": wallet_address}):
            users.append(user)
        return users
    
    async def add_fill(self, fill_data: dict):
        """Store fill data for analytics."""
        # Create a unique ID or use existing one to prevent duplicates
        # WsFill has 'tid' (trade id) or 'oid' (order id) + 'coin' + 'side'?
        # The documentation says tid is unique trade id.
        # We should use 'tid' as unique index if possible, or compound.
        # fill_data likely comes from WsFill.
        
        # We'll use upsert based on tid to avoid dupes if we reconnect
        tid = fill_data.get("tid")
        if tid:
            await self.fills.update_one(
                {"tid": tid},
                {"$set": fill_data},
                upsert=True
            )
        else:
            # Fallback if no tid
            await self.fills.insert_one(fill_data)

    async def get_fills(self, wallet_address: str, start_time: float, end_time: float):
        """Get fills for a wallet within a time range."""
        cursor = self.fills.find({
            "user": wallet_address,  # Assuming we store the user address in fill_data as 'user'
            "time": {"$gte": start_time * 1000, "$lte": end_time * 1000} # API uses millis
        })
        return await cursor.to_list(length=None)

    async def get_fills_range(self, wallet_address: str, start_time: float, end_time: float, limit: int = 20000):
        cursor = (
            self.fills.find({
                "user": wallet_address,
                "time": {"$gte": start_time * 1000, "$lte": end_time * 1000}
            })
            .sort("time", 1)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def get_fills_before(self, wallet_address: str, end_time: float, limit: int = 20000):
        cursor = (
            self.fills.find({
                "user": wallet_address,
                "time": {"$lte": end_time * 1000}
            })
            .sort("time", 1)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def get_fills_by_coin(self, wallet_address: str, coin: str, limit: int = 5000):
        """Get recent fills for a wallet/coin (best-effort for avg entry calculations)."""
        cursor = (
            self.fills.find({"user": wallet_address, "coin": coin})
            .sort("time", -1)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

db = Database()
