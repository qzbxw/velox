"""
RSS Engine — centralised feed registry, async fetch with ETag caching,
BBC-style GUID deduplication, and per-category article cache.

Usage:
    from bot.rss_engine import rss_engine
    articles = await rss_engine.fetch_all(since_hours=12)
    cached   = rss_engine.get_cached_articles(categories=["crypto"], limit=20)
"""

import asyncio
import calendar
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import quote_plus

import aiohttp
import feedparser

from bot.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Feed Registry
# ---------------------------------------------------------------------------

@dataclass
class FeedConfig:
    name: str
    url: str
    category: str
    tier: int = 2           # 1 = critical, 2 = standard, 3 = optional/noisy
    lang: str = "en"
    enabled: bool = True


# fmt: off
FEED_REGISTRY: list[FeedConfig] = [
    # ── CRYPTO Tier-1 ────────────────────────────────────────────────────
    FeedConfig("CoinDesk",          "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml", "crypto", 1),
    FeedConfig("Cointelegraph",     "https://cointelegraph.com/rss",                                 "crypto", 1),
    FeedConfig("Decrypt",           "https://decrypt.co/feed",                                       "crypto", 1),
    FeedConfig("The Block",         "https://www.theblock.co/rss.xml",                               "crypto", 1),
    FeedConfig("Bitcoin Magazine",  "https://bitcoinmagazine.com/.rss/full/",                        "crypto", 1),
    # ── CRYPTO Tier-2 ────────────────────────────────────────────────────
    FeedConfig("CryptoSlate",       "https://cryptoslate.com/feed/",        "crypto"),
    FeedConfig("Blockworks",        "https://blockworks.co/feed/",          "crypto"),
    FeedConfig("NewsBTC",           "https://www.newsbtc.com/feed/",        "crypto"),
    FeedConfig("U.Today",           "https://u.today/rss",                  "crypto"),
    FeedConfig("Crypto Briefing",   "https://cryptobriefing.com/feed/",     "crypto"),
    FeedConfig("Cryptopolitan",     "https://www.cryptopolitan.com/feed/",  "crypto"),
    FeedConfig("Bitcoinist",        "https://bitcoinist.com/feed/",         "crypto"),
    FeedConfig("BeInCrypto",        "https://beincrypto.com/feed/",         "crypto"),
    FeedConfig("CoinGape",          "https://coingape.com/feed/",           "crypto"),
    FeedConfig("The Daily Hodl",    "https://dailyhodl.com/feed/",          "crypto"),
    # ── DeFi / On-chain ──────────────────────────────────────────────────
    FeedConfig("The Defiant",       "https://thedefiant.io/api/feed",                  "defi", 1),
    FeedConfig("Glassnode Insights","https://insights.glassnode.com/rss/",             "defi", 1),
    FeedConfig("Chainalysis Blog",  "https://www.chainalysis.com/blog/feed",           "defi"),
    FeedConfig("Deribit Insights",  "https://insights.deribit.com/feed/",              "defi"),
    FeedConfig("Coin Metrics",      "https://coinmetrics.substack.com/feed",           "defi"),
    FeedConfig("a16z Crypto",       "https://a16zcrypto.substack.com/feed",            "defi"),
    FeedConfig("The Daily Gwei",    "https://thedailygwei.substack.com/feed",          "defi", 3),
    # ── REGULATORY ────────────────────────────────────────────────────────
    FeedConfig("Elliptic Blog",     "https://www.elliptic.co/blog/rss.xml",            "regulatory"),
    # ── POLITICS ──────────────────────────────────────────────────────────
    FeedConfig("POLITICO Politics", "https://rss.politico.com/politics-news.xml",      "politics", 1),
    FeedConfig("POLITICO Playbook", "https://rss.politico.com/playbook.xml",           "politics"),
    FeedConfig("NPR Politics",     "https://feeds.npr.org/1014/rss.xml",              "politics"),
    FeedConfig("The Hill",         "https://thehill.com/news/feed/",                   "politics"),
    FeedConfig("ProPublica",       "https://www.propublica.org/feeds/propublica/main", "politics", 3),
    FeedConfig("RealClearPolitics","https://www.realclearpolitics.com/index.xml",      "politics"),
    FeedConfig("Reason",           "https://reason.com/feed/",                         "politics", 3),
    # ── MACRO / FINANCE ──────────────────────────────────────────────────
    FeedConfig("BBC Business",     "http://feeds.bbci.co.uk/news/business/rss.xml",    "macro", 1),
    FeedConfig("BBC World",        "http://feeds.bbci.co.uk/news/world/rss.xml",       "macro", 1),
    FeedConfig("AP News Top",      "https://feedx.net/rss/ap.xml",                     "macro", 1),
    FeedConfig("Investing.com",    "https://www.investing.com/rss/news.rss",           "macro"),
    FeedConfig("Investing Crypto", "https://www.investing.com/rss/news_301.rss",       "macro"),
    FeedConfig("MarketWatch",      "http://feeds.marketwatch.com/marketwatch/topstories/", "macro"),
    FeedConfig("Yahoo Finance",    "https://finance.yahoo.com/news/rssindex",          "macro", 3),
    # ── TECH ──────────────────────────────────────────────────────────────
    FeedConfig("TechCrunch",       "https://techcrunch.com/feed",                      "tech"),
    FeedConfig("Ars Technica",     "http://feeds.arstechnica.com/arstechnica/index/",  "tech"),
    FeedConfig("Wired",            "https://www.wired.com/feed/rss",                   "tech", 3),
    FeedConfig("The Verge",        "https://www.theverge.com/rss/index.xml",           "tech", 3),
    # ── RESEARCH ──────────────────────────────────────────────────────────
    FeedConfig("Messari",          "https://messari.io/rss",                           "research", 1),
    FeedConfig("ForkLog EN",       "https://forklog.com/en/rss/",                      "research"),
    FeedConfig("MarkTechPost",     "https://www.marktechpost.com/feed/",               "research", 3),
    FeedConfig("Google AI Blog",   "https://blog.google/technology/ai/rss/",           "research", 3),
    # ── RU NEWS (влияет на крипто-рынок) ──────────────────────────────────
    FeedConfig("Коммерсантъ",      "https://www.kommersant.ru/RSS/main.xml",           "ru_news", 2, "ru"),
    FeedConfig("Meduza",           "https://meduza.io/rss/all",                        "ru_news", 2, "ru"),
    FeedConfig("Moscow Times",     "https://www.themoscowtimes.com/rss/news",          "ru_news", 2, "en"),
    FeedConfig("Lenta.ru",         "https://lenta.ru/rss",                             "ru_news", 3, "ru"),
    FeedConfig("Газета.ru",        "https://www.gazeta.ru/export/rss/first.xml",       "ru_news", 3, "ru"),
    FeedConfig("ТАСС",             "https://tass.com/rss/v2.xml",                      "ru_news", 3, "ru"),
    FeedConfig("Bits.media",       "https://bits.media/rss/news.xml",                  "ru_news", 3, "ru"),
]
# fmt: on

# Google News dynamic queries (kept from original)
GOOGLE_NEWS_QUERIES: list[dict] = [
    {"query": "crypto market",                "category": "crypto"},
    {"query": "bitcoin",                      "category": "crypto"},
    {"query": "ethereum",                     "category": "crypto"},
    {"query": "hyperliquid",                  "category": "crypto"},
    {"query": "spot bitcoin etf",             "category": "crypto"},
    {"query": "us politics economy",          "category": "politics"},
    {"query": "federal reserve interest rate", "category": "macro"},
    {"query": "white house crypto",           "category": "regulatory"},
    {"query": "crypto regulation",            "category": "regulatory"},
    {"query": "sec crypto",                   "category": "regulatory"},
    {"query": "cftc crypto",                  "category": "regulatory"},
]

# Source domain → display name (for Google News attribution)
SOURCE_DOMAINS: dict[str, str] = {
    "decrypt.co": "Decrypt",
    "coindesk.com": "CoinDesk",
    "cointelegraph.com": "Cointelegraph",
    "theblock.co": "The Block",
    "bitcoinmagazine.com": "Bitcoin Magazine",
    "newsbtc.com": "NewsBTC",
    "cryptoslate.com": "CryptoSlate",
    "u.today": "U.Today",
    "blockworks.co": "Blockworks",
    "cryptobriefing.com": "Crypto Briefing",
    "cryptopolitan.com": "Cryptopolitan",
    "bitcoinist.com": "Bitcoinist",
    "beincrypto.com": "BeInCrypto",
    "coingape.com": "CoinGape",
    "dailyhodl.com": "The Daily Hodl",
    "thedefiant.io": "The Defiant",
    "insights.glassnode.com": "Glassnode",
    "chainalysis.com": "Chainalysis",
    "coinmetrics.substack.com": "Coin Metrics",
    "insights.deribit.com": "Deribit Insights",
    "elliptic.co": "Elliptic",
    "politico.com": "POLITICO",
    "npr.org": "NPR",
    "realclearpolitics.com": "RealClearPolitics",
    "reason.com": "Reason",
    "thehill.com": "The Hill",
    "propublica.org": "ProPublica",
    "bbci.co.uk": "BBC",
    "bbc.co.uk": "BBC",
    "investing.com": "Investing.com",
    "marketwatch.com": "MarketWatch",
    "finance.yahoo.com": "Yahoo Finance",
    "techcrunch.com": "TechCrunch",
    "arstechnica.com": "Ars Technica",
    "wired.com": "Wired",
    "theverge.com": "The Verge",
    "messari.io": "Messari",
    "forklog.com": "ForkLog",
    "marktechpost.com": "MarkTechPost",
    "blog.google": "Google AI",
    "kommersant.ru": "Коммерсантъ",
    "meduza.io": "Meduza",
    "themoscowtimes.com": "Moscow Times",
    "lenta.ru": "Lenta.ru",
    "gazeta.ru": "Газета.ru",
    "tass.com": "ТАСС",
    "bits.media": "Bits.media",
    "news.google.com": "Google News",
    "feedx.net": "AP News",
}

CATEGORY_ORDER = ["crypto", "defi", "regulatory", "politics", "macro", "tech", "research", "ru_news"]
CATEGORY_LABELS = {
    "crypto": "🪙 CRYPTO",
    "defi": "🔗 DeFi / ON-CHAIN",
    "regulatory": "⚖️ REGULATORY",
    "politics": "🏛️ POLITICS",
    "macro": "📈 MACRO / FINANCE",
    "tech": "💻 TECH",
    "research": "🔬 RESEARCH",
    "ru_news": "🇷🇺 RU NEWS",
}

# Browser-like headers to avoid 403
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


# ---------------------------------------------------------------------------
#  RSSEngine
# ---------------------------------------------------------------------------

class RSSEngine:
    """Async RSS aggregator with ETag caching and deduplication."""

    def __init__(self):
        # ETag / Last-Modified cache:  url -> (etag, last_modified)
        self._etag_cache: dict[str, tuple[str, str]] = {}
        # Cached articles (populated by fetch_all)
        self._article_cache: list[dict] = []
        self._cache_ts: float = 0.0
        # Dedup sets persisted across fetches (reset on TTL expiry)
        self._seen_guids: set[str] = set()
        self._seen_titles: set[str] = set()
        # Google News feeds (built once)
        self._google_feeds: list[FeedConfig] = self._build_google_news_feeds()
        # Concurrency limiter for network requests
        self._semaphore = asyncio.Semaphore(20)

    # -- Google News feed builder ------------------------------------------

    @staticmethod
    def _build_google_news_feeds() -> list[FeedConfig]:
        feeds = []
        for item in GOOGLE_NEWS_QUERIES:
            q = item["query"]
            encoded = quote_plus(f"{q} when:1d")
            feeds.append(FeedConfig(
                name=f"Google News: {q}",
                url=f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en",
                category=item["category"],
                tier=2,
            ))
        return feeds

    # -- All active feeds --------------------------------------------------

    def _all_feeds(self) -> list[FeedConfig]:
        active = [f for f in FEED_REGISTRY if f.enabled]
        return active + self._google_feeds

    # -- Single feed fetch with ETag / 304 support -------------------------

    async def _fetch_single(
        self,
        session: aiohttp.ClientSession,
        feed: FeedConfig,
        since_ts: float,
    ) -> list[dict]:
        url = feed.url
        headers = dict(_HEADERS)

        # Add conditional headers
        cached = self._etag_cache.get(url)
        if cached:
            etag, last_mod = cached
            if etag:
                headers["If-None-Match"] = etag
            if last_mod:
                headers["If-Modified-Since"] = last_mod

        async with self._semaphore:
            try:
                timeout = aiohttp.ClientTimeout(total=settings.RSS_FETCH_TIMEOUT)
                async with session.get(url, headers=headers, timeout=timeout, allow_redirects=True) as resp:
                    if resp.status == 304:
                        # Not modified — skip parsing
                        return []

                    if resp.status != 200:
                        if resp.status not in (301, 302, 403, 503):
                            logger.warning("RSS %s returned %d", feed.name, resp.status)
                        return []

                    # Update ETag cache
                    new_etag = resp.headers.get("ETag", "")
                    new_lm = resp.headers.get("Last-Modified", "")
                    if new_etag or new_lm:
                        self._etag_cache[url] = (new_etag, new_lm)

                    content = await resp.text()
            except asyncio.TimeoutError:
                logger.warning("RSS timeout: %s", feed.name)
                return []
            except Exception as e:
                logger.error("RSS fetch error %s: %s", feed.name, e)
                return []

        # Parse XML
        parsed = feedparser.parse(content)
        if parsed.bozo:
            logger.debug("Bozo for %s: %s", feed.name, parsed.bozo_exception)

        return self._process_entries(feed, parsed.entries, since_ts)

    # -- Entry processing & dedup ------------------------------------------

    @staticmethod
    def _normalize_guid(guid: str) -> str:
        """Strip BBC-style anchor suffixes like #0, #1, #2."""
        return re.sub(r"#\d+$", "", guid).strip()

    @staticmethod
    def _extract_source(entry, link: str, fallback: str) -> str:
        source_meta = getattr(entry, "source", None)
        if source_meta:
            title = ""
            if isinstance(source_meta, dict):
                title = (source_meta.get("title") or "").strip()
            else:
                title = (getattr(source_meta, "title", "") or "").strip()
            if title:
                return title[:80]

        for domain, name in SOURCE_DOMAINS.items():
            if domain in link:
                return name
        return fallback

    def _process_entries(
        self,
        feed: FeedConfig,
        entries: list,
        since_ts: float,
    ) -> list[dict]:
        articles = []
        for entry in entries:
            link = getattr(entry, "link", "") or ""
            title = (getattr(entry, "title", "") or "").strip()
            if not title:
                continue

            # --- Dedup by GUID / link ---
            raw_guid = getattr(entry, "id", "") or link
            guid = self._normalize_guid(raw_guid)
            if guid and guid in self._seen_guids:
                continue

            # --- Dedup by normalised title ---
            t_norm = re.sub(r"\s+", " ", title.lower())
            if t_norm in self._seen_titles:
                continue

            # --- Parse published time ---
            pub_ts = 0.0
            try:
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_ts = float(calendar.timegm(entry.published_parsed))
                elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                    pub_ts = float(calendar.timegm(entry.updated_parsed))
            except Exception:
                pass

            if pub_ts and pub_ts < since_ts:
                continue

            # Commit to dedup sets
            if guid:
                self._seen_guids.add(guid)
            self._seen_titles.add(t_norm)

            articles.append({
                "title": title,
                "link": link,
                "source": self._extract_source(entry, link, feed.name),
                "category": feed.category,
                "tier": feed.tier,
                "lang": feed.lang,
                "published": pub_ts or time.time(),
                "summary": (getattr(entry, "summary", "") or "")[:600],
            })
        return articles

    # -- Main public API ---------------------------------------------------

    async def fetch_all(self, since_hours: float = 12) -> list[dict]:
        """
        Fetch ALL enabled feeds in parallel and return deduplicated articles.
        Updates internal cache.
        """
        since_ts = time.time() - since_hours * 3600
        feeds = self._all_feeds()

        # Expire old dedup sets if cache is older than TTL
        ttl = settings.RSS_ARTICLE_TTL_HOURS * 3600
        if time.time() - self._cache_ts > ttl:
            self._seen_guids.clear()
            self._seen_titles.clear()

        from bot.services import get_session
        session = await get_session()

        tasks = [self._fetch_single(session, f, since_ts) for f in feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_articles: list[dict] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Feed %s exception: %s", feeds[i].name, result)
                continue
            all_articles.extend(result)

        # Sort by publish time descending
        all_articles.sort(key=lambda x: x["published"], reverse=True)

        # Update cache
        self._article_cache = all_articles
        self._cache_ts = time.time()

        logger.info(
            "RSS Engine: fetched %d articles from %d feeds (%.1fs ago cutoff)",
            len(all_articles), len(feeds), since_hours * 3600,
        )
        return all_articles

    def get_cached_articles(
        self,
        categories: list[str] | None = None,
        limit: int = 50,
        tier_max: int = 3,
    ) -> list[dict]:
        """Return cached articles filtered by category and tier."""
        arts = self._article_cache
        if categories:
            cats = set(categories)
            arts = [a for a in arts if a["category"] in cats]
        if tier_max < 3:
            arts = [a for a in arts if a["tier"] <= tier_max]
        return arts[:limit]

    @property
    def cache_age_seconds(self) -> float:
        return time.time() - self._cache_ts if self._cache_ts else float("inf")

    @property
    def cached_count(self) -> int:
        return len(self._article_cache)

    # -- Formatting helpers (moved from market_overview) -------------------

    def format_digest(self, articles: list[dict], limit: int = 10) -> str:
        """Simple flat list of headlines."""
        if not articles:
            return "No RSS headlines."
        lines = []
        for item in articles[:limit]:
            title = item.get("title", "").strip()
            source = item.get("source", "").strip()
            if title:
                lines.append(f"- {title} ({source})")
        return "\n".join(lines) if lines else "No RSS headlines."

    def format_digest_by_category(
        self,
        articles: list[dict],
        per_category_limits: dict[str, int] | None = None,
    ) -> str:
        """Grouped by category with limits per section."""
        if not articles:
            return "No RSS headlines."

        limits = per_category_limits or {
            "crypto": 8, "defi": 4, "regulatory": 3,
            "politics": 3, "macro": 4, "tech": 2,
            "research": 2, "ru_news": 2,
        }

        sections = []
        for cat in CATEGORY_ORDER:
            cap = limits.get(cat, 0)
            if cap <= 0:
                continue

            lines = []
            for item in articles:
                if item.get("category") != cat:
                    continue
                title = item.get("title", "").strip()
                source = item.get("source", "").strip()
                if not title:
                    continue
                lines.append(f"- {title} ({source})")
                if len(lines) >= cap:
                    break

            if lines:
                label = CATEGORY_LABELS.get(cat, cat.upper())
                sections.append(f"{label}:\n" + "\n".join(lines))

        return "\n\n".join(sections) if sections else "No RSS headlines."


# ---------------------------------------------------------------------------
#  Module-level singleton
# ---------------------------------------------------------------------------

rss_engine = RSSEngine()
