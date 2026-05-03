from __future__ import annotations

import hashlib
import time

from bot.agent.context import SourceItem, to_plain
from bot.config import settings
from bot.database import db


def source_cache_key(tool: str, key: str) -> str:
    return hashlib.sha1(f"{tool}:{key}".encode("utf-8")).hexdigest()


class SourceCache:
    async def put(self, tool: str, item: SourceItem) -> None:
        ttl_min = int(getattr(settings, "AGENT_SOURCE_CACHE_TTL_MIN", 60) or 60)
        await db.save_agent_source_cache({
            "cache_key": source_cache_key(tool, item.url or item.title),
            "tool": tool,
            "url": item.url,
            "source": to_plain(item),
            "created_at": time.time(),
            "expires_at": time.time() + ttl_min * 60,
        })

    async def put_many(self, tool: str, items: list[SourceItem]) -> None:
        for item in items:
            await self.put(tool, item)
