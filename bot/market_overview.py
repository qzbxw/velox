import aiohttp
import asyncio
import logging
import time
import json
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import re
from urllib.parse import quote_plus
from bot.config import settings
from bot.services import pretty_float

logger = logging.getLogger(__name__)

class MarketOverview:
    def __init__(self):
        # Main Hedge Agent - analyzes and responds
        self.hedge_agent_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemma-4-31b-it:generateContent?key={settings.GEMINI_API_KEY}"

        # News Agent - collects fresh news via Google Search
        self.news_agent_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent?key={settings.GEMINI_API_KEY}"
        self.enable_search_news = settings.MARKET_OVERVIEW_ENABLE_SEARCH_NEWS

        self.publisher_rss_feeds = [
            {"name": "Decrypt", "url": "https://decrypt.co/feed", "category": "crypto"},
            {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "category": "crypto"},
            {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss", "category": "crypto"},
            {"name": "The Block", "url": "https://www.theblock.co/rss.xml", "category": "crypto"},
            {"name": "Bitcoin Magazine", "url": "https://bitcoinmagazine.com/.rss/full/", "category": "crypto"},
            {"name": "NewsBTC", "url": "https://www.newsbtc.com/feed/", "category": "crypto"},
            {"name": "CryptoSlate", "url": "https://cryptoslate.com/feed/", "category": "crypto"},
            {"name": "U.Today", "url": "https://u.today/rss", "category": "crypto"},
            {"name": "Blockworks", "url": "https://blockworks.co/feed/", "category": "crypto"},
            {"name": "Crypto Briefing", "url": "https://cryptobriefing.com/feed/", "category": "crypto"},
            {"name": "Cryptopolitan", "url": "https://www.cryptopolitan.com/feed/", "category": "crypto"},
            {"name": "Bitcoinist", "url": "https://bitcoinist.com/feed/", "category": "crypto"},
            {"name": "BeInCrypto", "url": "https://beincrypto.com/feed/", "category": "crypto"},
            {"name": "CoinGape", "url": "https://coingape.com/feed/", "category": "crypto"},
            {"name": "The Daily Hodl", "url": "https://dailyhodl.com/feed/", "category": "crypto"},
            {"name": "The Defiant", "url": "https://thedefiant.io/api/feed", "category": "crypto"},
            {"name": "Glassnode Insights", "url": "https://insights.glassnode.com/rss/", "category": "crypto"},
            {"name": "Chainalysis Reports", "url": "https://blog.chainalysis.com/reports/feed/", "category": "crypto"},
            {"name": "Coin Metrics", "url": "https://coinmetrics.substack.com/feed", "category": "crypto"},
            {"name": "Deribit Insights", "url": "https://insights.deribit.com/feed/", "category": "crypto"},
            {"name": "a16z Crypto", "url": "https://a16zcrypto.substack.com/feed", "category": "crypto"},
            {"name": "The Daily Gwei", "url": "https://thedailygwei.substack.com/feed", "category": "crypto"},
            {"name": "Elliptic Blog", "url": "https://www.elliptic.co/blog/rss.xml", "category": "regulatory"},
            {"name": "POLITICO Politics", "url": "https://rss.politico.com/politics-news.xml", "category": "politics"},
            {"name": "POLITICO Playbook", "url": "https://rss.politico.com/playbook.xml", "category": "politics"},
            {"name": "NPR Politics", "url": "https://feeds.npr.org/1014/rss.xml", "category": "politics"},
            {"name": "RealClearPolitics", "url": "https://www.realclearpolitics.com/index.xml", "category": "politics"},
            {"name": "Reason", "url": "https://reason.com/feed/", "category": "politics"},
        ]
        self.topic_rss_queries = [
            {"query": "crypto market", "category": "crypto"},
            {"query": "bitcoin", "category": "crypto"},
            {"query": "ethereum", "category": "crypto"},
            {"query": "hyperliquid", "category": "crypto"},
            {"query": "spot bitcoin etf", "category": "crypto"},
            {"query": "us politics", "category": "politics"},
            {"query": "federal reserve", "category": "politics"},
            {"query": "white house crypto", "category": "politics"},
            {"query": "crypto regulation", "category": "regulatory"},
            {"query": "sec crypto", "category": "regulatory"},
            {"query": "cftc crypto", "category": "regulatory"},
            {"query": "congress crypto regulation", "category": "regulatory"},
        ]
        self.category_order = ["crypto", "politics", "regulatory"]
        self.category_labels = {
            "crypto": "CRYPTO",
            "politics": "POLITICS",
            "regulatory": "REGULATORY",
        }
        self.source_domains = {
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
            "insights.glassnode.com": "Glassnode Insights",
            "blog.chainalysis.com": "Chainalysis Reports",
            "coinmetrics.substack.com": "Coin Metrics",
            "insights.deribit.com": "Deribit Insights",
            "a16zcrypto.substack.com": "a16z Crypto",
            "thedailygwei.substack.com": "The Daily Gwei",
            "elliptic.co": "Elliptic Blog",
            "politico.com": "POLITICO",
            "npr.org": "NPR Politics",
            "realclearpolitics.com": "RealClearPolitics",
            "reason.com": "Reason",
            "news.google.com": "Google News",
        }
        self.rss_feeds = self.publisher_rss_feeds + self._build_google_news_feeds()
        # Common browser headers to avoid 403 Forbidden
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
        }
        self._toxic_patterns = [
            r"\bidiot\b", r"\bstupid\b", r"\btrash\b", r"\bpoor\b", r"\bloser\b",
            r"\bni[\w-]*brod\b", r"\bговн\w*\b", r"\bжалк\w*\b", r"\bнищ\w*\b"
        ]

    def _build_google_news_feeds(self) -> list[dict]:
        feeds = []
        for item in self.topic_rss_queries:
            query = item["query"]
            encoded_query = quote_plus(f"{query} when:1d")
            feeds.append({
                "name": f"Google News: {query}",
                "url": f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en",
                "category": item["category"],
            })
        return feeds

    async def fetch_etf_flows(self) -> dict:
        """
        Scrapes ETF flows from Farside Investors.
        Returns: {
            "btc_flow": float (in Millions),
            "eth_flow": float (in Millions),
            "btc_date": str,
            "eth_date": str
        }
        """
        # Default fallback
        result = {
            "btc_flow": 0.0,
            "eth_flow": 0.0,
            "btc_date": "N/A",
            "eth_date": "N/A"
        }

        async def fetch_farside(url):
            try:
                logger.info(f"Fetching Farside URL: {url}")
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=self.headers, timeout=15) as resp:
                        logger.info(f"Farside {url} Status: {resp.status}")
                        if resp.status == 200:
                            text = await resp.text()
                            logger.info(f"Farside HTML length: {len(text)}")
                            logger.debug(f"Farside HTML snippet: {text[:500]}...") 
                            return text
                        else:
                            logger.warning(f"Farside returned status {resp.status} for {url}")
            except Exception as e:
                logger.error(f"Failed to fetch Farside {url}: {e}")
            return None

        btc_html, eth_html = await asyncio.gather(
            fetch_farside(settings.FARSIDE_BTC_URL),
            fetch_farside(settings.FARSIDE_ETH_URL),
            return_exceptions=True
        )

        if isinstance(btc_html, str):
            flow, date = self._parse_farside_html(btc_html)
            if flow is not None:
                result["btc_flow"] = flow
                result["btc_date"] = date
        
        if isinstance(eth_html, str):
            flow, date = self._parse_farside_html(eth_html)
            if flow is not None:
                result["eth_flow"] = flow
                result["eth_date"] = date

        return result

    def _parse_farside_html(self, html: str) -> tuple[float | None, str | None]:
        """
        Parses Farside HTML to find the latest daily flow.
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Farside often has multiple tables. The main data is usually in a table with class 'table' or just a big table.
            tables = soup.find_all('table')
            
            for table in tables:
                # Try to find 'Total' column index from headers
                headers = [th.get_text(strip=True).lower() for th in table.find_all('th')]
                total_col_idx = -1
                
                # Look for "Total" or "Flow" in headers
                for i, h in enumerate(headers):
                    if "total" in h and "net" in h: # "Total Net Flow"
                        total_col_idx = i
                        break
                if total_col_idx == -1:
                     for i, h in enumerate(headers):
                        if "total" in h: # Just "Total" (often 'Total' is the aggregate column)
                            total_col_idx = i
                            break
                
                # If we didn't find a Total column, check if this table looks like the right one (has dates)
                # Some tables are just summaries. We want daily data.
                
                rows = table.find_all('tr')
                # Iterate rows from bottom up (latest usually at bottom)
                for row in reversed(rows):
                    cols = row.find_all(['td', 'th'])
                    if not cols:
                        continue
                    
                    date_text = cols[0].get_text(strip=True)
                    # Check if it looks like a date (digits involved)
                    if not re.search(r'\d', date_text):
                        continue
                    
                    # Get value
                    flow_val = None
                    
                    if total_col_idx != -1 and total_col_idx < len(cols):
                        txt = cols[total_col_idx].get_text(strip=True)
                        flow_val = self._clean_number(txt)
                    
                    # Fallback: try last column if we have > 2 columns
                    if flow_val is None and len(cols) > 2:
                        txt = cols[-1].get_text(strip=True)
                        flow_val = self._clean_number(txt)
                    
                    if flow_val is not None:
                        return flow_val, date_text
                        
        except Exception as e:
            logger.error(f"Error parsing Farside HTML: {e}")
            
        return None, None

    def _clean_number(self, text: str) -> float | None:
        try:
            # Remove ( ) for negative, $ for currency, commas
            if not text:
                return None
            t = text.replace('$', '').replace(',', '')
            if '(' in t and ')' in t:
                t = '-' + t.replace('(', '').replace(')', '')
            return float(t)
        except (TypeError, ValueError):
            return None

    async def fetch_news_rss(self, since_timestamp: float = 0) -> list[dict]:
        """
        Fetches news from RSS feeds published after since_timestamp.
        """
        articles = []
        
        async def fetch_feed(session: aiohttp.ClientSession, feed_cfg: dict):
            url = feed_cfg["url"]
            try:
                async with session.get(url, headers=self.headers, timeout=15) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        feed = feedparser.parse(content)
                        if feed.bozo:
                            logger.warning(f"Feedparser bozo exception for {url}: {feed.bozo_exception}")
                        return feed_cfg, feed.entries
                    else:
                        logger.warning(f"RSS fetch failed {resp.status} for {url}")
            except Exception as e:
                logger.error(f"Failed to fetch RSS {url}: {e}")
            return feed_cfg, []

        async with aiohttp.ClientSession() as session:
            results = await asyncio.gather(
                *[fetch_feed(session, feed_cfg) for feed_cfg in self.rss_feeds],
                return_exceptions=True
            )
        
        seen_links = set()
        seen_titles = set()

        for result in results:
            if isinstance(result, Exception):
                continue
            feed_cfg, entries = result
            if not entries:
                continue
            for entry in entries:
                # Deduplicate by link
                link = getattr(entry, "link", "") or ""
                title = (getattr(entry, "title", "") or "").strip()
                t_norm = re.sub(r"\s+", " ", title.lower())
                if link in seen_links or (t_norm and t_norm in seen_titles):
                    continue
                if link:
                    seen_links.add(link)
                if t_norm:
                    seen_titles.add(t_norm)

                # Parse published time
                try:
                    pub_ts = 0
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        import calendar
                        pub_ts = calendar.timegm(entry.published_parsed)
                    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                        import calendar
                        pub_ts = calendar.timegm(entry.updated_parsed)
                    
                    if pub_ts < since_timestamp:
                        continue
                        
                    articles.append({
                        "title": title,
                        "link": link,
                        "source": self._extract_source(entry, link, feed_cfg.get("name", "News")),
                        "category": feed_cfg.get("category", "crypto"),
                        "published": pub_ts,
                        "summary": getattr(entry, 'summary', '')[:1000]
                    })
                except Exception:
                    continue
        
        # Sort by date desc
        articles.sort(key=lambda x: x["published"], reverse=True)
        return articles

    def _extract_source(self, entry, link: str, fallback: str = "News") -> str:
        source_meta = getattr(entry, "source", None)
        if source_meta:
            if isinstance(source_meta, dict):
                source_title = (source_meta.get("title") or "").strip()
            else:
                source_title = (getattr(source_meta, "title", "") or "").strip()
            if source_title:
                return source_title[:80]

        for domain, source_name in self.source_domains.items():
            if domain in link:
                return source_name
        return fallback

    def _format_news_digest(self, news: list[dict], limit: int = 10) -> str:
        if not news:
            return "No RSS headlines."
        lines = []
        for item in news[:limit]:
            title = (item.get("title") or "").strip()
            source = (item.get("source") or "News").strip()
            if not title:
                continue
            lines.append(f"- {title} ({source})")
        return "\n".join(lines) if lines else "No RSS headlines."

    def _format_news_digest_by_category(self, news: list[dict], per_category_limits: dict[str, int]) -> str:
        if not news:
            return "No RSS headlines."

        sections = []
        for category in self.category_order:
            limit = int(per_category_limits.get(category, 0) or 0)
            if limit <= 0:
                continue

            lines = []
            for item in news:
                if item.get("category", "crypto") != category:
                    continue
                title = (item.get("title") or "").strip()
                source = (item.get("source") or "News").strip()
                if not title:
                    continue
                lines.append(f"- {title} ({source})")
                if len(lines) >= limit:
                    break

            if lines:
                sections.append(f"{self.category_labels.get(category, category.upper())}:\n" + "\n".join(lines))

        return "\n\n".join(sections) if sections else "No RSS headlines."

    def _sanitize_comment(self, text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"\s+", " ", text).strip()
        for p in self._toxic_patterns:
            if re.search(p, cleaned, flags=re.IGNORECASE):
                return "Risk is elevated. Avoid emotional decisions, reduce size, and wait for confirmation before acting."
        return cleaned[:900]

    def _is_stable_asset(self, symbol: str) -> bool:
        s = str(symbol or "").upper().replace(" (MARGIN)", "").strip()
        return s in {"USDC", "USDT", "USDE", "FDUSD", "DAI", "USD"}

    def _normalize_symbol(self, symbol: str) -> str:
        s = str(symbol or "").upper().replace(" (MARGIN)", "").strip()
        if s.startswith("@"):
            s = s[1:]
        if "/" in s:
            s = s.split("/", 1)[0]
        return s

    async def _build_user_context_snapshot(self, wallets: list[str]) -> dict:
        from bot.services import get_spot_balances, get_perps_state, get_symbol_name

        if not wallets:
            return {
                "summary": "No wallet data.",
                "positions": [],
                "position_symbols": set(),
                "stable_assets": [],
                "risk_assets": [],
                "has_open_positions": False,
            }

        results = await asyncio.gather(*[
            asyncio.gather(get_spot_balances(wallet), get_perps_state(wallet), return_exceptions=True)
            for wallet in wallets
        ])

        positions = []
        risk_assets = []
        stable_assets = []
        margin_rows = []

        for wallet, result in zip(wallets, results):
            if not isinstance(result, (list, tuple)) or len(result) != 2:
                continue

            spot, perps = result

            if isinstance(spot, list):
                for balance in spot:
                    total = float(balance.get("total", 0) or 0)
                    if total <= 0:
                        continue

                    coin_id = balance.get("coin")
                    symbol = await get_symbol_name(coin_id, is_spot=True)
                    item = f"{symbol}={pretty_float(total, 4)}"

                    if self._is_stable_asset(symbol):
                        stable_assets.append(item)
                    else:
                        risk_assets.append(item)

            if isinstance(perps, dict):
                margin_summary = perps.get("marginSummary", {}) or {}
                equity = float(margin_summary.get("accountValue", 0) or 0)
                margin_used = float(margin_summary.get("totalMarginUsed", 0) or 0)
                ntl = float(margin_summary.get("totalNtlPos", 0) or 0)

                if equity > 0:
                    util = (margin_used / equity) * 100 if equity > 0 else 0.0
                    margin_rows.append(
                        f"{wallet[:6]}... util {util:.0f}% | eq ${pretty_float(equity, 0)} | ntl ${pretty_float(ntl, 0)}"
                    )

                for wrapper in perps.get("assetPositions", []) or []:
                    pos = wrapper.get("position", {}) or {}
                    size = float(pos.get("szi", 0) or 0)
                    if size == 0:
                        continue

                    coin_id = pos.get("coin")
                    symbol = await get_symbol_name(coin_id, is_spot=False)
                    entry = float(pos.get("entryPx", 0) or 0)
                    leverage = float((pos.get("leverage") or {}).get("value", 0) or 0)
                    liquidation = float(pos.get("liquidationPx", 0) or 0)
                    upnl = float(
                        pos.get("unrealizedPnl", pos.get("unrealizedPnlUsd", pos.get("returnOnEquity", 0))) or 0
                    )
                    notional = abs(float(pos.get("positionValue", 0) or 0)) or abs(size * entry)

                    positions.append({
                        "symbol": symbol,
                        "wallet": wallet,
                        "side": "LONG" if size > 0 else "SHORT",
                        "size": size,
                        "entry": entry,
                        "leverage": leverage,
                        "liquidation": liquidation,
                        "upnl": upnl,
                        "notional": notional,
                    })

        positions.sort(key=lambda item: item.get("notional", 0), reverse=True)
        risk_assets = risk_assets[:8]
        stable_assets = stable_assets[:4]
        margin_rows = margin_rows[:4]

        position_lines = []
        for item in positions[:8]:
            liq_part = f" | liq {pretty_float(item['liquidation'], 2)}" if item["liquidation"] > 0 else ""
            lev_part = f"{item['leverage']:.1f}x" if item["leverage"] > 0 else "spot"
            position_lines.append(
                f"{item['symbol']} {item['side']} size {pretty_float(abs(item['size']), 4)} @ {pretty_float(item['entry'], 2)} | {lev_part}{liq_part}"
            )

        summary_parts = [
            f"Open perps ({len(positions)}): " + (", ".join(position_lines) if position_lines else "none"),
            "Risk assets: " + (", ".join(risk_assets) if risk_assets else "none"),
            "Stable assets: " + (", ".join(stable_assets) if stable_assets else "none"),
            "Margin: " + (" ; ".join(margin_rows) if margin_rows else "no margin data"),
        ]

        return {
            "summary": "\n".join(summary_parts),
            "positions": positions,
            "position_symbols": {self._normalize_symbol(item.get("symbol", "")) for item in positions if item.get("symbol")},
            "stable_assets": stable_assets,
            "risk_assets": risk_assets,
            "has_open_positions": bool(positions),
        }

    async def fetch_news_with_search(self, timeframe: str = "24h", topics: list = None) -> str:
        """
        News Agent: Collects fresh crypto news via Google Search tool.
        Returns: Structured news summary from Google Search
        """
        if not self.enable_search_news or not settings.GEMINI_API_KEY:
            return ""

        if topics is None:
            topics = ["Hyperliquid", "Bitcoin", "Ethereum", "crypto market"]

        topic_str = ", ".join(topics)

        prompt = f"""You are a News Agent. Search for the latest {timeframe} crypto news related to: {topic_str}.

Focus on:
- Major price movements and market events
- Important protocol updates or launches
- Regulatory news
- Institutional activity (ETFs, large purchases)
- Technical developments

Provide a concise summary with key bullet points."""

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 1024
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.news_agent_url, json=payload, timeout=25) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        candidate = data["candidates"][0]
                        text = candidate["content"]["parts"][0]["text"].strip()

                        # Extract grounding metadata if available for transparency
                        grounding_meta = candidate.get("groundingMetadata", {})
                        if grounding_meta:
                            logger.info(f"News Agent received groundingMetadata with {len(grounding_meta.get('groundingChunks', []))} chunks")
                            
                        return text
                    else:
                        error_text = await resp.text()
                        logger.error(f"News Agent error: {resp.status} - {error_text}")
        except Exception as e:
            logger.error(f"News Agent exception: {e}")

        return ""

    async def generate_summary(self,
                             market_data: dict,
                             news: list[dict],
                             period_name: str,
                             custom_prompt: str | None = None,
                             style: str = "detailed",
                             lang: str = "en") -> dict:
        """
        Hedge Agent: RAG system that combines market data + fresh news.
        """
        target_lang = "Russian" if lang == "ru" else "English"

        # Step 1: Use RSS headlines as the primary news layer and optional Search enrichment
        logger.info("News digest: Building RSS-first market context...")
        topics = ["Hyperliquid", "Bitcoin", "Ethereum", "crypto market"]

        # Add top gainers/losers to search topics
        if market_data.get('top_gainers'):
            for g in market_data['top_gainers'][:2]:
                topics.append(g.get('name', ''))
        
        fresh_news = await self.fetch_news_with_search(timeframe="24h", topics=topics)
        rss_news = self._format_news_digest_by_category(
            news,
            per_category_limits={"crypto": 6, "politics": 2, "regulatory": 3},
        )
        combined_news = f"RSS HEADLINES:\n{rss_news}\n\nSEARCH DIGEST:\n{fresh_news or 'No search digest'}"

        # Step 2: Hedge Agent analyzes everything
        logger.info("Hedge Agent: Generating grounded analysis...")
        prompt = f"""
        You are VELOX AI, an institutional analyst. Use the PROVIDED DATA and NEWS to analyze Hyperliquid L1.

        PERIOD: {period_name}
        LANGUAGE: {target_lang}
        STYLE: {style}
        {f"USER CUSTOM STYLE: {custom_prompt}" if custom_prompt else ""}

        MARKET DATA:
        - 24h Volume: ${market_data.get('global_volume', 'N/A')}
        - Total OI: ${market_data.get('total_oi', 'N/A')}
        - Top Gainers: {', '.join([f"{g['name']} {g['change']}%" for g in market_data.get('top_gainers', [])[:3]])}
        - ETF Flows: BTC ${market_data.get('etf_flows', {}).get('btc_flow', 0)}M, ETH ${market_data.get('etf_flows', {}).get('eth_flow', 0)}M

        NEWS INTELLIGENCE:
        {combined_news}

        TASK:
        Synthesize market data + news into actionable intelligence.

        RESPONSE REQUIREMENTS (JSON):
        1. "summary": Sharp analysis connecting market moves to news. Use **bold** for key assets.
        2. "sentiment": BULLISH, BEARISH, NEUTRAL, CAUTIOUS, or EXPLOSIVE.
        3. "next_event": Key milestone to watch (max 100 chars).
        """

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "response_mime_type": "application/json",
                "thinking_config": {
                    "thinking_level": "HIGH"
                }
            }
        }
        if self.enable_search_news:
            payload["tools"] = [{"google_search": {}}]

        default_res = {
            "summary": "Market data processing complete. Sentiment remains mixed as volatility clusters around major assets.",
            "sentiment": "NEUTRAL",
            "next_event": "Watch for consolidation at current levels."
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.hedge_agent_url, json=payload, timeout=20) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        # Gemma 4 thinking mode returns parts. Final answer is usually the last text part.
                        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                        text = ""
                        for part in parts:
                            if "text" in part and not part.get("thought"):
                                text = part["text"].strip()
                        
                        if not text and parts:
                            text = parts[-1].get("text", "").strip()

                        # Clean markdown if present
                        if "```json" in text:
                            text = text.split("```json")[1].split("```")[0].strip()

                        if not text:
                            return default_res

                        parsed = json.loads(text)

                        # Handle list wrapping
                        if isinstance(parsed, list):
                            if len(parsed) > 0 and isinstance(parsed[0], dict):
                                return parsed[0]
                            else:
                                return default_res

                        if isinstance(parsed, dict):
                            return parsed

                        return default_res
                    else:
                        logger.error(f"Hedge Agent error: {resp.status} - {await resp.text()}")
        except Exception as e:
            logger.error(f"Hedge Agent exception: {e}")

        return default_res

    async def generate_hedge_comment(self, 
                                   context_type: str, 
                                   event_data: dict, 
                                   user_id: int, 
                                   lang: str = "en",
                                   history: list = None) -> str:
        """
        Generates a contextual AI comment for Velox Hedge.
        context_type: 'liquidation', 'fill', 'proximity', 'volatility', 'whale', 'margin', 'listing', 'ledger', 'funding', 'chat'
        """
        from bot.database import db
        
        # 1. Fetch User Context
        wallets = await db.list_wallets(user_id)
        snapshot = await self._build_user_context_snapshot(wallets)
        portfolio_summary = snapshot["summary"]

        watchlist = await db.get_watchlist(user_id) or []
        watchlist_str = ", ".join(watchlist) if watchlist else "empty"
        memory = await db.get_hedge_memory(user_id, limit=12)
        if context_type == "chat":
            memory_items = memory
        else:
            memory_items = [m for m in memory if m.get("role") in ("system", "user")]
        memory_txt = "\n".join(
            [f"- {m.get('role', 'system')}: {str(m.get('content', ''))[:220]}" for m in memory_items if m.get("content")]
        ) or "No prior context."

        # 2. Fetch Style (Prompt Override)
        ov_settings = await db.get_overview_settings(user_id)
        custom_style = ov_settings.get("prompt_override", "Professional and sharp.")
        
        # 3. Build fresh news context
        event_symbol = self._normalize_symbol(event_data.get('symbol', event_data.get('sym', '')))
        matching_positions = [
            p for p in snapshot["positions"]
            if self._normalize_symbol(p.get("symbol", "")) == event_symbol
        ] if event_symbol else []
        watchlist_match = bool(event_symbol and event_symbol in {self._normalize_symbol(w) for w in watchlist})

        topics = ["crypto market"]
        if event_symbol:
            topics.append(event_symbol)

        logger.info(f"Hedge Chat: Building RSS-first news context for context_type={context_type}")
        search_task = self.fetch_news_with_search(timeframe="12h", topics=topics)
        rss_news, fresh_news = await asyncio.gather(
            self.fetch_news_rss(since_timestamp=time.time() - 12 * 3600),
            search_task,
        )
        news_digest = self._format_news_digest_by_category(
            rss_news,
            per_category_limits={"crypto": 5, "politics": 1, "regulatory": 2},
        )

        target_lang = "Russian" if lang == "ru" else "English"

        if matching_positions:
            match_summary = "; ".join(
                [
                    f"{p['symbol']} {p['side']} {pretty_float(abs(p['size']), 4)} @ {pretty_float(p['entry'], 2)} | {p['leverage']:.1f}x"
                    for p in matching_positions[:4]
                ]
            )
            relevance_hint = f"Direct exposure detected in open perps: {match_summary}"
        elif event_symbol and watchlist_match:
            relevance_hint = f"No open perp in {event_symbol}, but the symbol is in the user's watchlist."
        elif event_symbol and snapshot["has_open_positions"]:
            relevance_hint = f"No direct {event_symbol} perp position. Compare this event against current open perps before giving advice."
        elif snapshot["has_open_positions"]:
            relevance_hint = "User has open perp positions. Frame the event through current directional exposure and margin."
        else:
            relevance_hint = "No open perp positions. Avoid generic comfort lines; focus on whether the event creates a setup worth watching."

        # 4. Construct RAG prompt
        prompt = f"""
        You are VELOX ASSISTANT, an elite market and risk assistant with real-time news access.
        NON-NEGOTIABLE RULES:
        - Never insult, mock, humiliate, or use toxic language.
        - Never mention user's "poverty", "small balance", or similar.
        - Be factual and uncertainty-aware: avoid guaranteed predictions.
        - Keep output <= 320 characters for non-chat contexts.
        - If data is weak, say so briefly and give a conservative action.
        - Never say "risk zero", "no risk", "safe because of USDC", or any equivalent.
        - Do not default to commenting on stablecoin balance unless it is directly relevant to the event.
        - If the user has open positions, prioritize those positions over idle spot balances.
        - Use the event symbol, side, leverage, liquidation, margin, or watchlist relevance when available.
        - If there is no direct exposure, say that briefly and then give the most relevant next action.
        USER STYLE/PROMPT: {custom_style}
        TARGET LANGUAGE: {target_lang}

        USER CONTEXT:
        - Portfolio: {portfolio_summary}
        - Watchlist: {watchlist_str}
        - Event relevance hint: {relevance_hint}

        RECENT MEMORY (latest interactions):
        {memory_txt}

        MARKET NEWS (RSS + Search):
        RSS:
        {news_digest}
        SEARCH:
        {fresh_news or "No search digest"}

        EVENT TYPE: {context_type.upper()}
        EVENT DATA: {json.dumps(event_data)}
        """
        
        if context_type == 'chat':
            prompt += (
                f"\nCHAT HISTORY:\n{json.dumps(history if history else [])}\n"
                "ACTION: Reply to the user's latest message considering all context. "
                "If the user asks about risk or positions, anchor your answer in their actual open positions first, then cash/watchlist context."
            )
        else:
            prompt += (
                "\nACTION: Provide a very brief (max 300 chars), sharp, and actionable insight about this event. "
                "Start with direct portfolio relevance. If there is direct exposure, mention the matching position or risk first. "
                "If there is no direct exposure, say that once and pivot to a concrete watch/hedge/entry-risk idea. "
                "Avoid generic reassurance."
            )

        prompt += "\nOUTPUT: Plain text only, no JSON, no headers. Use Markdown **bolding** for emphasis."

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.45}
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.hedge_agent_url, json=payload, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                        return self._sanitize_comment(text)
        except Exception as e:
            logger.error(f"Hedge Chat error: {e}")
        return ""

market_overview = MarketOverview()
