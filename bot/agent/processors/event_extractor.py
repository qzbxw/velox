from __future__ import annotations

import json
import logging
import re
from typing import Any

from bot.agent.context import AgentRunContext, MarketEvent, SourceItem
from bot.config import settings
from bot.services import get_session

logger = logging.getLogger(__name__)


def strip_json_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return text


def parse_events_json(raw: str) -> list[MarketEvent]:
    parsed = json.loads(strip_json_fences(raw))
    if isinstance(parsed, dict):
        parsed = parsed.get("events", [])
    if not isinstance(parsed, list):
        return []
    return [MarketEvent.from_dict(item) for item in parsed if isinstance(item, dict)]


class EventExtractor:
    async def extract(self, context: AgentRunContext, sources: list[SourceItem]) -> list[MarketEvent]:
        if not getattr(settings, "GEMINI_API_KEY", ""):
            return self.fallback_extract(sources)

        cards = [
            {
                "title": s.title,
                "source": s.source,
                "url": s.url,
                "snippet": s.snippet[:500],
                "assets": s.assets,
                "published_ts": s.published_ts,
            }
            for s in sources[:30]
        ]
        prompt = (
            "Extract market-moving crypto events from these source cards. "
            "Return JSON list only. Each object must include title, category, assets, "
            "summary, sentiment, impact, confidence, source_urls, published_ts. "
            "Allowed category: macro, regulatory, institutional, onchain, derivatives, "
            "protocol, security, market_structure, asset_specific, other. "
            "Allowed sentiment: bullish, bearish, neutral, mixed. "
            "Allowed impact: low, medium, high, critical.\n\n"
            f"SOURCES:\n{json.dumps(cards, ensure_ascii=False)}"
        )
        model = getattr(settings, "AGENT_EVENT_EXTRACTOR_MODEL", "gemini-3.1-flash-lite-preview")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.GEMINI_API_KEY}"
        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }
        try:
            session = await get_session()
            async with session.post(url, json=payload, timeout=getattr(settings, "AGENT_TOOL_TIMEOUT_SEC", 15)) as resp:
                if resp.status != 200:
                    context.add_error("extract_market_events", f"LLM status {resp.status}")
                    return self.fallback_extract(sources)
                data = await resp.json()
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
                return parse_events_json(text)
        except Exception as exc:
            logger.debug("Event extraction failed", exc_info=True)
            context.add_error("extract_market_events", exc)
            return self.fallback_extract(sources)

    def fallback_extract(self, sources: list[SourceItem]) -> list[MarketEvent]:
        events: list[MarketEvent] = []
        for source in sources[:8]:
            text = " ".join([source.title, source.snippet]).lower()
            category = "asset_specific"
            if any(k in text for k in ("etf", "flows", "blackrock", "institutional")):
                category = "institutional"
            elif any(k in text for k in ("sec", "cftc", "regulation", "lawsuit")):
                category = "regulatory"
            elif any(k in text for k in ("fed", "inflation", "rates")):
                category = "macro"
            sentiment = "neutral"
            if any(k in text for k in ("surge", "inflow", "rally", "approval", "record")):
                sentiment = "bullish"
            elif any(k in text for k in ("hack", "outflow", "drop", "lawsuit", "liquidation")):
                sentiment = "bearish"
            events.append(MarketEvent(
                title=source.title[:180],
                category=category,
                assets=source.assets,
                summary=source.snippet[:500] or source.title,
                sentiment=sentiment,
                impact="medium",
                confidence=0.45,
                source_urls=[source.url] if source.url else [],
                published_ts=source.published_ts,
            ))
        return events
