from __future__ import annotations

from bot.services import get_fear_greed_index


class FearGreedTool:
    name = "fear_greed"

    async def collect(self) -> dict:
        return await get_fear_greed_index()
