from __future__ import annotations

import json
import logging
from typing import Any

from bot.agent.context import (
    AgentRunContext,
    MarketEvent,
    MarketRegime,
    MarketSnapshot,
    PortfolioRelevantEvent,
    SourceItem,
    to_plain,
)
from bot.agent.processors.event_extractor import strip_json_fences
from bot.config import settings
from bot.services import get_session

logger = logging.getLogger(__name__)


REQUIRED_OUTPUT_KEYS = {
    "summary", "sentiment", "regime", "top_risks", "top_opportunities",
    "portfolio_relevance", "next_event", "actionable_notes", "sources"
}


def deterministic_report(
    snapshot: MarketSnapshot,
    regime: MarketRegime,
    events: list[MarketEvent],
    relevance: list[PortfolioRelevantEvent],
    sources: list[SourceItem],
    lang: str = "en",
) -> dict[str, Any]:
    top_events = events[:5]
    sentiment = "NEUTRAL"
    bullish = sum(1 for e in top_events if e.sentiment == "bullish")
    bearish = sum(1 for e in top_events if e.sentiment == "bearish")
    if regime.regime == "risk_on" or bullish > bearish:
        sentiment = "BULLISH"
    elif regime.regime == "risk_off" or bearish > bullish:
        sentiment = "BEARISH"
    summary = regime.summary
    if top_events:
        summary += " Key event: " + top_events[0].summary[:240]
    return {
        "summary": summary,
        "sentiment": sentiment,
        "regime": regime.regime,
        "top_risks": [e.title for e in top_events if e.sentiment in {"bearish", "mixed"}][:5],
        "top_opportunities": [e.title for e in top_events if e.sentiment in {"bullish", "mixed"}][:5],
        "portfolio_relevance": [r.reason for r in relevance[:5]],
        "next_event": top_events[0].title[:100] if top_events else "Watch ETF flows, funding, and BTC/ETH reaction.",
        "actionable_notes": [
            "Size risk around confirmed market direction.",
            "Check funding and OI before adding leverage.",
        ],
        "sources": [{"title": s.title, "url": s.url, "source": s.source} for s in sources[:8]],
    }


async def synthesize_final_report(
    context: AgentRunContext,
    snapshot: MarketSnapshot,
    regime: MarketRegime,
    events: list[MarketEvent],
    relevance: list[PortfolioRelevantEvent],
    sources: list[SourceItem],
) -> dict[str, Any]:
    fallback = deterministic_report(snapshot, regime, events, relevance, sources, context.lang)
    if not getattr(settings, "GEMINI_API_KEY", ""):
        return fallback
    compact = {
        "lang": context.lang,
        "snapshot": to_plain(snapshot),
        "regime": to_plain(regime),
        "events": [to_plain(e) for e in events[:12]],
        "portfolio_relevance": [to_plain(r) for r in relevance[:8]],
        "sources": [{"title": s.title, "url": s.url, "source": s.source, "snippet": s.snippet[:250]} for s in sources[:12]],
    }
    prompt = (
        "Synthesize this structured market intelligence into JSON only with exactly these keys: "
        "summary, sentiment, regime, top_risks, top_opportunities, portfolio_relevance, "
        "next_event, actionable_notes, sources. Use concise institutional tone. "
        f"Generation style: {context.style or 'detailed'}. "
        f"{'User generation instructions: ' + context.custom_prompt.strip() + ' ' if context.custom_prompt else ''}"
        f"Data:\n{json.dumps(compact, ensure_ascii=False)}"
    )
    model = getattr(settings, "AGENT_LLM_MODEL", "gemma-4-31b-it")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    try:
        session = await get_session()
        async with session.post(url, json=payload, timeout=getattr(settings, "AGENT_PIPELINE_TIMEOUT_SEC", 120)) as resp:
            if resp.status != 200:
                context.add_error("synthesize_final_report", f"LLM status {resp.status}")
                return fallback
            data = await resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
            parsed = json.loads(strip_json_fences(text))
            if not isinstance(parsed, dict):
                return fallback
            for key in REQUIRED_OUTPUT_KEYS:
                parsed.setdefault(key, fallback[key])
            return {key: parsed[key] for key in REQUIRED_OUTPUT_KEYS}
    except Exception as exc:
        logger.debug("Final synthesis failed", exc_info=True)
        context.add_error("synthesize_final_report", exc)
        return fallback
