from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

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

_HTML_LINK_RE = re.compile(r"<a\s+[^>]*href=[\"'][^\"']+[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_BROKEN_HTML_LINK_RE = re.compile(r"<a\s+href=[\"'][^\"']*$", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:https?://|www\.)[^)\s]+(?:\s+\"[^\"]*\")?\)")
_BARE_URL_RE = re.compile(r"(?:https?://|www\.)\S+")


def _clean_text(value: Any, max_len: int | None = None) -> str:
    text = str(value or "")
    text = re.sub(_HTML_LINK_RE, r"\1", text)
    text = re.sub(_MARKDOWN_LINK_RE, r"\1", text)
    text = re.sub(_BROKEN_HTML_LINK_RE, "", text)
    text = re.sub(_HTML_TAG_RE, "", text)
    text = re.sub(_BARE_URL_RE, "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"\s+", " ", text).strip(" -–—\n\t")
    if max_len and len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0].strip()
    return text


def _clean_url(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return url
    return ""


def _clean_list(value: Any, limit: int = 5, max_len: int = 220) -> list[str]:
    raw_items = value if isinstance(value, list) else ([value] if value else [])
    cleaned = [_clean_text(item, max_len=max_len) for item in raw_items]
    return [item for item in cleaned if item][:limit]


def _source_cards(sources: list[SourceItem], limit: int = 8) -> list[dict[str, str]]:
    cards = []
    for source in sources[:limit]:
        title = _clean_text(source.title or source.source or "Source", max_len=160)
        source_name = _clean_text(source.source or "", max_len=80)
        url = _clean_url(source.url)
        if title or url:
            cards.append({"title": title or source_name or "Source", "url": url, "source": source_name})
    return cards


def normalize_report_output(output: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    base = fallback or {}
    normalized = {key: output.get(key, base.get(key)) for key in REQUIRED_OUTPUT_KEYS}
    normalized["summary"] = _clean_text(normalized.get("summary"), max_len=1200) or _clean_text(base.get("summary"), max_len=1200)
    normalized["sentiment"] = (_clean_text(normalized.get("sentiment"), max_len=40) or "NEUTRAL").upper()
    normalized["regime"] = _clean_text(normalized.get("regime"), max_len=80) or "neutral"
    normalized["top_risks"] = _clean_list(normalized.get("top_risks"))
    normalized["top_opportunities"] = _clean_list(normalized.get("top_opportunities"))
    normalized["portfolio_relevance"] = _clean_list(normalized.get("portfolio_relevance"))
    normalized["next_event"] = _clean_text(normalized.get("next_event"), max_len=180) or _clean_text(base.get("next_event"), max_len=180)
    normalized["actionable_notes"] = _clean_list(normalized.get("actionable_notes"), max_len=180)

    source_items = normalized.get("sources")
    sources = []
    if isinstance(source_items, list):
        for item in source_items[:8]:
            if not isinstance(item, dict):
                continue
            title = _clean_text(item.get("title") or item.get("source") or "Source", max_len=160)
            source = _clean_text(item.get("source") or "", max_len=80)
            url = _clean_url(item.get("url"))
            if title or url:
                sources.append({"title": title or source or "Source", "url": url, "source": source})
    normalized["sources"] = sources
    return {key: normalized[key] for key in REQUIRED_OUTPUT_KEYS}


def _event_label(event: MarketEvent) -> str:
    title = _clean_text(event.title, max_len=120)
    summary = _clean_text(event.summary, max_len=160)
    if summary and summary.lower() != title.lower():
        return summary
    return title


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

    drivers = [str(driver) for driver in regime.main_drivers[:3] if driver]
    event_labels = [_event_label(event) for event in top_events[:3]]
    event_labels = [label for label in event_labels if label]
    regime_name = regime.regime.replace("_", "-")
    if event_labels:
        summary = (
            f"Market regime is {regime_name} with {sentiment.lower()} skew. "
            f"Main drivers: {', '.join(drivers) if drivers else 'mixed spot momentum and uneven event flow'}. "
            f"Watch: {'; '.join(event_labels)}."
        )
    else:
        summary = (
            f"Market regime is {regime_name} with {sentiment.lower()} skew. "
            f"Main drivers: {', '.join(drivers) if drivers else 'mixed majors momentum and incomplete confirmation'}."
        )

    report = {
        "summary": summary,
        "sentiment": sentiment,
        "regime": regime.regime,
        "top_risks": [_event_label(e) for e in top_events if e.sentiment in {"bearish", "mixed"}][:5],
        "top_opportunities": [_event_label(e) for e in top_events if e.sentiment in {"bullish", "mixed"}][:5],
        "portfolio_relevance": [r.reason for r in relevance[:5]],
        "next_event": _event_label(top_events[0]) if top_events else "Watch ETF flows, funding, and BTC/ETH reaction.",
        "actionable_notes": [
            "Treat the regime as transitional until price action and flows confirm the same direction.",
            "Check funding, open interest, and ETF flow reaction before adding leverage.",
        ],
        "sources": _source_cards(sources),
    }
    return normalize_report_output(report)


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
        "Do not copy raw headlines as the whole answer. Do not put URLs, HTML, markdown links, "
        "or source citations inside summary, risks, opportunities, next_event, or actionable_notes. "
        "The summary must be an actual synthesis of regime, drivers, risks, and what to watch next. "
        "URLs are allowed only in sources[].url. "
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
            return normalize_report_output(parsed, fallback)
    except Exception as exc:
        logger.debug("Final synthesis failed", exc_info=True)
        context.add_error("synthesize_final_report", exc)
        return fallback
