from __future__ import annotations

from bot.agent.context import MarketSnapshot
from bot.services import get_perps_context


def _asset_name(item) -> str:
    return item.get("name") if isinstance(item, dict) else str(item)


class HyperliquidTool:
    name = "hyperliquid"

    async def collect_snapshot(self) -> MarketSnapshot:
        ctx = await get_perps_context()
        universe = []
        asset_ctxs = []
        if isinstance(ctx, dict):
            universe = ctx.get("universe", [])
            asset_ctxs = ctx.get("assetCtxs", [])
        elif isinstance(ctx, list) and len(ctx) == 2:
            universe = ctx[0].get("universe", []) if isinstance(ctx[0], dict) else ctx[0]
            asset_ctxs = ctx[1]

        rows = []
        total_volume = 0.0
        total_oi = 0.0
        majors = {}
        for i, item in enumerate(universe):
            if i >= len(asset_ctxs):
                continue
            ac = asset_ctxs[i] or {}
            name = _asset_name(item)
            price = float(ac.get("markPx", 0) or 0)
            prev = float(ac.get("prevDayPx", 0) or price)
            change = ((price - prev) / prev) * 100 if prev else 0.0
            volume = float(ac.get("dayNtlVlm", 0) or 0)
            oi = float(ac.get("openInterest", 0) or 0) * price
            funding = float(ac.get("funding", 0) or 0)
            row = {"name": name, "price": price, "change": round(change, 2), "volume": volume, "oi": oi, "funding": funding}
            rows.append(row)
            total_volume += volume
            total_oi += oi
            if name in {"BTC", "ETH", "SOL", "HYPE"}:
                majors[name] = row
        rows.sort(key=lambda r: r["change"], reverse=True)
        by_volume = sorted(rows, key=lambda r: r["volume"], reverse=True)
        by_funding = sorted(rows, key=lambda r: r["funding"], reverse=True)
        return MarketSnapshot(
            global_volume=total_volume,
            total_oi=total_oi,
            top_gainers=rows[:5],
            top_losers=list(reversed(rows[-5:])),
            highest_funding=by_funding[:5],
            highest_volume=by_volume[:5],
            majors=majors,
        )
