from __future__ import annotations

from bot.market_overview import market_overview


class FarsideTool:
    name = "farside"

    async def collect(self) -> dict:
        return await market_overview.fetch_etf_flows()
