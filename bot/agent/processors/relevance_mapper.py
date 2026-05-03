from __future__ import annotations

import asyncio

from bot.agent.context import MarketEvent, PortfolioExposure, PortfolioRelevantEvent
from bot.database import db
from bot.services import get_perps_state, get_spot_balances, get_symbol_name


def _norm_symbol(value: str) -> str:
    return str(value or "").upper().replace(" (MARGIN)", "").split("/", 1)[0].lstrip("@")


async def build_portfolio_exposure(user_id: int | str | None) -> PortfolioExposure:
    if not user_id:
        return PortfolioExposure()
    wallets = await db.list_wallets(user_id)
    watchlist = [_norm_symbol(s) for s in (await db.get_watchlist(user_id) or [])]
    exposure = PortfolioExposure(wallets=wallets, watchlist=watchlist)
    states = await asyncio.gather(*[
        asyncio.gather(get_spot_balances(wallet), get_perps_state(wallet), return_exceptions=True)
        for wallet in wallets
    ], return_exceptions=True)
    for wallet, state_pair in zip(wallets, states):
        if not isinstance(state_pair, (list, tuple)) or len(state_pair) != 2:
            continue
        spot, perps = state_pair
        if isinstance(spot, list):
            for balance in spot:
                total = float(balance.get("total", 0) or 0)
                if total <= 0:
                    continue
                symbol = await get_symbol_name(balance.get("coin"), is_spot=True)
                exposure.spot_balances.append({"wallet": wallet, **balance, "symbol": _norm_symbol(symbol)})
        if isinstance(perps, dict):
            for wrapper in perps.get("assetPositions", []) or []:
                pos = wrapper.get("position", {}) or {}
                size = float(pos.get("szi", 0) or 0)
                if size == 0:
                    continue
                symbol = await get_symbol_name(pos.get("coin"), is_spot=False)
                leverage = float((pos.get("leverage") or {}).get("value", 0) or 0)
                notional = abs(float(pos.get("positionValue", 0) or 0))
                exposure.perps_positions.append({
                    "wallet": wallet,
                    **pos,
                    "symbol": _norm_symbol(symbol),
                    "leverage_value": leverage,
                    "notional": notional,
                })
    return exposure


def map_portfolio_relevance(events: list[MarketEvent], exposure: PortfolioExposure) -> list[PortfolioRelevantEvent]:
    direct_perps = {_norm_symbol(p.get("symbol")): p for p in exposure.perps_positions}
    direct_spot = {_norm_symbol(b.get("symbol")): b for b in exposure.spot_balances}
    watch = {_norm_symbol(s) for s in exposure.watchlist}
    result: list[PortfolioRelevantEvent] = []
    for event in events:
        assets = {_norm_symbol(a) for a in event.assets}
        matched = sorted(assets & (set(direct_perps) | set(direct_spot) | watch))
        if not matched:
            continue
        score = 0.2
        exposure_type = "watchlist"
        reason = "Matched watchlist symbol."
        focus = "Monitor event follow-through before adding risk."
        for sym in matched:
            if sym in direct_perps:
                lev = float(direct_perps[sym].get("leverage_value", 0) or 0)
                score = max(score, 0.65 + min(0.25, lev / 40))
                exposure_type = "perp"
                reason = f"Direct perp exposure in {sym}."
                focus = "Check liquidation distance, funding, and whether event invalidates the trade."
            elif sym in direct_spot:
                score = max(score, 0.5)
                exposure_type = "spot"
                reason = f"Direct spot exposure in {sym}."
                focus = "Review spot sizing and whether news changes holding thesis."
        if event.impact in {"high", "critical"}:
            score = min(1.0, score + 0.15)
        result.append(PortfolioRelevantEvent(event, round(score, 2), exposure_type, matched, reason, focus))
    result.sort(key=lambda item: item.relevance_score, reverse=True)
    return result
