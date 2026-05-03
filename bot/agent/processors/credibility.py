from __future__ import annotations

import re
import time
from collections import Counter
from urllib.parse import urlsplit

from bot.agent.context import SourceItem, SourceScore


TIER_1_DOMAINS = {
    "coindesk.com", "cointelegraph.com", "theblock.co", "decrypt.co",
    "bitcoinmagazine.com", "blockworks.co", "thedefiant.io", "glassnode.com",
    "sec.gov", "cftc.gov", "federalreserve.gov", "farside.co.uk",
}
NOISY_DOMAINS = {"medium.com", "reddit.com", "x.com", "twitter.com", "youtube.com"}
ASSET_RE = re.compile(r"\b(BTC|ETH|SOL|HYPE|USDC|USDT|BNB|XRP|DOGE|AVAX|LINK|AAVE|UNI|ENA|PENDLE|JUP)\b", re.I)
MARKET_TERMS = {
    "bitcoin", "ethereum", "crypto", "etf", "flows", "funding", "open interest",
    "liquidation", "sec", "cftc", "fed", "federal reserve", "stablecoin",
    "hyperliquid", "defi", "regulation", "macro", "inflation",
}


def source_domain(item: SourceItem) -> str:
    return urlsplit(item.url or "").netloc.lower().removeprefix("www.")


def extract_assets(text: str) -> list[str]:
    return sorted({m.group(1).upper() for m in ASSET_RE.finditer(text or "")})


def _recency_score(published_ts: float | None) -> float:
    if not published_ts:
        return 0.45
    age_hours = max(0.0, (time.time() - float(published_ts)) / 3600)
    if age_hours <= 2:
        return 1.0
    if age_hours <= 12:
        return 0.85
    if age_hours <= 24:
        return 0.7
    if age_hours <= 72:
        return 0.45
    return 0.2


def _source_reputation(item: SourceItem) -> float:
    domain = source_domain(item)
    if domain in TIER_1_DOMAINS or item.source in {"CoinDesk", "The Block", "Decrypt", "Cointelegraph"}:
        return 1.0
    if domain in NOISY_DOMAINS:
        return 0.25
    if item.source_type in {"rss", "google_news_rss"}:
        return 0.7
    if item.source_type in {"api", "market_data"}:
        return 0.85
    return 0.55


def _market_relevance(item: SourceItem) -> tuple[float, list[str]]:
    text = " ".join([item.title, item.snippet, item.content]).lower()
    reasons = []
    matches = sum(1 for term in MARKET_TERMS if term in text)
    assets = extract_assets(text)
    if assets:
        reasons.append("asset match")
        item.assets = sorted(set(item.assets) | set(assets))
    if matches:
        reasons.append("market keyword match")
    return min(1.0, 0.2 + matches * 0.1 + len(assets) * 0.12), reasons


def score_sources(items: list[SourceItem]) -> list[tuple[SourceItem, SourceScore]]:
    topic_counts: Counter[str] = Counter()
    for item in items:
        text = " ".join([item.title, item.snippet, item.content])
        for asset in extract_assets(text):
            topic_counts[asset] += 1
        for term in MARKET_TERMS:
            if term in text.lower():
                topic_counts[term] += 1

    scored: list[tuple[SourceItem, SourceScore]] = []
    for item in items:
        reasons = []
        recency = _recency_score(item.published_ts)
        reputation = _source_reputation(item)
        relevance, relevance_reasons = _market_relevance(item)
        reasons.extend(relevance_reasons)
        text = " ".join([item.title, item.snippet, item.content]).lower()
        confirmations = 0
        for topic, count in topic_counts.items():
            if count > 1 and topic.lower() in text:
                confirmations += 1
        confirmation = min(1.0, confirmations * 0.2)
        final = round((recency * 0.25) + (reputation * 0.25) + (relevance * 0.35) + (confirmation * 0.15), 4)
        if reputation >= 0.9:
            reasons.append("high reputation source")
        if confirmation:
            reasons.append("cross-source confirmation")
        scored.append((item, SourceScore(recency, reputation, relevance, confirmation, final, reasons)))

    scored.sort(key=lambda pair: pair[1].final_score, reverse=True)
    return scored
