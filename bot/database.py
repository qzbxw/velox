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
                    "wallet_address": wallet_address,
                    "updated_at": time.time()
                },
                "$setOnInsert": {
                    "created_at": time.time()
                }
            },
            upsert=True
        )
        logger.info(f"User {chat_id} updated with wallet {wallet_address}")

    async def get_user(self, chat_id: int):
        return await self.users.find_one({"chat_id": chat_id})

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

db = Database()
