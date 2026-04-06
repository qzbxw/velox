"""
News Summarizer — AI subagent that pre-processes raw RSS articles
using a fast/cheap LLM (Flash-Lite) so the main Hedge Agent receives
a compact, scored digest instead of hundreds of raw headlines.

Usage:
    from bot.news_summarizer import news_summarizer
    digest = await news_summarizer.get_digest(articles, lang="en")
"""

import asyncio
import hashlib
import json
import logging
import time

import aiohttp

from bot.config import settings

logger = logging.getLogger(__name__)


class NewsSummarizer:
    """Pre-summarise & score RSS articles via a lightweight LLM."""

    def __init__(self):
        self._model_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.NEWS_SUMMARIZER_MODEL}:generateContent"
            f"?key={settings.GEMINI_API_KEY}"
        )
        # digest cache:  hash -> (text, timestamp)
        self._digest_cache: dict[str, tuple[str, float]] = {}
        self._cache_ttl = 1800  # 30 min

    # ------------------------------------------------------------------
    #  Cache helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _articles_hash(articles: list[dict]) -> str:
        """Deterministic fingerprint of a batch of articles."""
        titles = "|".join(a.get("title", "")[:80] for a in articles[:60])
        return hashlib.md5(titles.encode()).hexdigest()

    def _get_cached(self, key: str) -> str | None:
        entry = self._digest_cache.get(key)
        if entry and time.time() - entry[1] < self._cache_ttl:
            return entry[0]
        return None

    def _put_cache(self, key: str, value: str):
        self._digest_cache[key] = (value, time.time())
        # Evict old entries
        if len(self._digest_cache) > 50:
            oldest = sorted(self._digest_cache, key=lambda k: self._digest_cache[k][1])
            for k in oldest[:20]:
                del self._digest_cache[k]

    # ------------------------------------------------------------------
    #  Core summarization
    # ------------------------------------------------------------------

    async def summarize_batch(
        self,
        articles: list[dict],
        lang: str = "en",
        context: str = "crypto market analysis",
    ) -> str:
        """
        Send a batch of article headlines+summaries to Flash-Lite
        and receive a compact, scored digest.

        Returns a structured text block ready to be inserted into
        the main Hedge Agent's prompt.
        """
        if not articles:
            return "No news available."

        if not settings.NEWS_SUMMARIZER_ENABLED or not settings.GEMINI_API_KEY:
            # Fallback: simple concatenation without AI
            return self._fallback_digest(articles, lang)

        cache_key = self._articles_hash(articles) + f":{lang}"
        cached = self._get_cached(cache_key)
        if cached:
            logger.debug("News Summarizer: cache hit")
            return cached

        # Build input for the summarizer
        items_text = self._prepare_items(articles)
        target_lang = "Russian" if lang == "ru" else "English"

        prompt = f"""You are a financial news analyst AI. Your task is to process raw RSS headlines and produce a concise, actionable intelligence brief.

INPUT: {len(articles)} news items from various sources about {context}.

{items_text}

TASK:
1. Identify the 6-10 MOST IMPORTANT stories that could impact crypto/financial markets
2. For each, determine: sentiment (BULL / BEAR / NEUTRAL), impact level (HIGH / MED / LOW)
3. Group by topic cluster (e.g. "BTC ETF", "Fed Policy", "DeFi Exploit")
4. Output in {target_lang}

FORMAT your output as a structured brief:
[TOPIC CLUSTER] (SENTIMENT, IMPACT)
• Key headline summary — Source
• Related development — Source

Keep the TOTAL output under 600 words. Focus on market-moving information only.
Omit trivial announcements, opinion pieces, and duplicate stories."""

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 1200,
            },
        }

        try:
            from bot.services import get_session
            session = await get_session()
            async with session.post(
                self._model_url, json=payload, timeout=aiohttp.ClientTimeout(total=90)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    text = (
                        data.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")
                        .strip()
                    )
                    if text:
                        self._put_cache(cache_key, text)
                        logger.info(
                            "News Summarizer: produced %d-char digest from %d articles",
                            len(text), len(articles),
                        )
                        return text
                else:
                    err = await resp.text()
                    logger.error("News Summarizer API error %d: %s", resp.status, err[:300])
        except Exception as e:
            logger.error("News Summarizer exception: %s", e)

        # Fallback on error
        return self._fallback_digest(articles, lang)

    # ------------------------------------------------------------------
    #  High-level API for consumers
    # ------------------------------------------------------------------

    async def get_digest(
        self,
        articles: list[dict],
        lang: str = "en",
        per_category_limits: dict[str, int] | None = None,
    ) -> str:
        """
        Main entry point.  Takes raw articles from RSSEngine,
        filters by limits, runs AI summarization, returns digest.
        """
        if per_category_limits:
            filtered = self._filter_by_category(articles, per_category_limits)
        else:
            # Default: take top articles by tier and recency
            filtered = sorted(articles, key=lambda a: (-a.get("tier", 2), -a.get("published", 0)))
            filtered = filtered[:60]

        return await self.summarize_batch(filtered, lang=lang)

    # ------------------------------------------------------------------
    #  Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_by_category(articles: list[dict], limits: dict[str, int]) -> list[dict]:
        result = []
        counters: dict[str, int] = {}
        for a in articles:
            cat = a.get("category", "crypto")
            cap = limits.get(cat, 0)
            if cap <= 0:
                continue
            count = counters.get(cat, 0)
            if count >= cap:
                continue
            result.append(a)
            counters[cat] = count + 1
        return result

    @staticmethod
    def _prepare_items(articles: list[dict]) -> str:
        lines = []
        for i, a in enumerate(articles[:60], 1):
            src = a.get("source", "")
            cat = a.get("category", "")
            title = a.get("title", "")
            # Include first 120 chars of summary if available
            summary = (a.get("summary", "") or "")[:120]
            summary_part = f" | {summary}" if summary else ""
            lines.append(f"{i}. [{cat.upper()}] {title} — {src}{summary_part}")
        return "\n".join(lines)

    @staticmethod
    def _fallback_digest(articles: list[dict], lang: str = "en") -> str:
        """Simple headline list when AI is unavailable."""
        if not articles:
            return "No news available."
        lines = []
        for a in articles[:15]:
            title = a.get("title", "").strip()
            source = a.get("source", "").strip()
            if title:
                lines.append(f"- {title} ({source})")
        return "\n".join(lines) if lines else "No news available."


# ---------------------------------------------------------------------------
#  Module-level singleton
# ---------------------------------------------------------------------------

news_summarizer = NewsSummarizer()
