from __future__ import annotations

from bot.agent.context import MarketEvent, to_plain
from bot.database import db


class EventStore:
    async def upsert_many(self, events: list[MarketEvent]) -> None:
        for event in events:
            await db.upsert_market_event(to_plain(event))

    async def recent(self, limit: int = 50) -> list[dict]:
        return await db.list_recent_market_events(limit=limit)
