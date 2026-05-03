from __future__ import annotations

from bot.agent.context import MarketEvent, MarketRegime, MarketSnapshot


def classify_market_regime(snapshot: MarketSnapshot, events: list[MarketEvent]) -> MarketRegime:
    score = 0.0
    drivers: list[str] = []
    for sym in ("BTC", "ETH", "SOL", "HYPE"):
        change = float(snapshot.majors.get(sym, {}).get("change", 0) or 0)
        score += change * (0.35 if sym in {"BTC", "ETH"} else 0.15)
    fg = snapshot.fear_greed or {}
    fg_value = float(fg.get("value", 50) or 50)
    if fg_value >= 70:
        score += 1.0
        drivers.append("elevated Fear & Greed")
    elif fg_value <= 30:
        score -= 1.0
        drivers.append("weak Fear & Greed")
    flows = snapshot.etf_flows or {}
    etf_total = float(flows.get("btc_flow", 0) or 0) + float(flows.get("eth_flow", 0) or 0)
    if etf_total > 100:
        score += 1.0
        drivers.append("positive ETF flows")
    elif etf_total < -100:
        score -= 1.0
        drivers.append("negative ETF flows")
    for event in events[:10]:
        weight = {"low": 0.15, "medium": 0.3, "high": 0.6, "critical": 1.0}.get(event.impact, 0.3)
        if event.sentiment == "bullish":
            score += weight
        elif event.sentiment == "bearish":
            score -= weight
    if score >= 2.0:
        regime = "risk_on"
    elif score <= -2.0:
        regime = "risk_off"
    elif abs(score) >= 0.8:
        regime = "transitional"
    else:
        regime = "neutral"
    confidence = min(0.9, 0.45 + abs(score) * 0.08)
    if not drivers:
        drivers = ["mixed majors momentum", "event flow not one-sided"]
    return MarketRegime(
        regime=regime,
        confidence=round(confidence, 2),
        summary=f"{regime.replace('_', ' ').title()} regime with score {score:.2f}.",
        main_drivers=drivers[:5],
    )
