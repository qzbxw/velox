import aiohttp
import asyncio
import logging
import time
import json
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import re
from bot.config import settings
from bot.services import pretty_float

logger = logging.getLogger(__name__)

class MarketOverview:
    def __init__(self):
        # Main Hedge Agent - analyzes and responds
        self.hedge_agent_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={settings.GEMINI_API_KEY}"

        # News Agent - collects fresh news via Google Search
        self.news_agent_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={settings.GEMINI_API_KEY}"

        self.rss_feeds = [
            "https://decrypt.co/feed",
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            "https://cointelegraph.com/rss",
            "https://cryptopanic.com/news/rss/",
            "https://www.theblock.co/rss.xml",
            "https://bitcoinmagazine.com/.rss/full/",
            "https://blog.coinbase.com/feed",
            "https://www.binance.com/en/feed/rss",
            "https://messari.io/rss",
            "https://www.coinglass.com/learn/rss.xml",
            "https://www.newsbtc.com/feed/",
            "https://cryptoslate.com/feed/",
            "https://u.today/rss"
        ]
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
                    if not cols: continue
                    
                    date_text = cols[0].get_text(strip=True)
                    # Check if it looks like a date (digits involved)
                    if not re.search(r'\d', date_text): continue
                    
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
            if not text: return None
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
        
        async def fetch_feed(session: aiohttp.ClientSession, url: str):
            try:
                async with session.get(url, headers=self.headers, timeout=15) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        feed = feedparser.parse(content)
                        if feed.bozo:
                            logger.warning(f"Feedparser bozo exception for {url}: {feed.bozo_exception}")
                        return feed.entries
                    else:
                        logger.warning(f"RSS fetch failed {resp.status} for {url}")
            except Exception as e:
                logger.error(f"Failed to fetch RSS {url}: {e}")
            return []

        async with aiohttp.ClientSession() as session:
            results = await asyncio.gather(*[fetch_feed(session, url) for url in self.rss_feeds], return_exceptions=True)
        
        seen_links = set()
        seen_titles = set()

        for entries in results:
            if isinstance(entries, Exception):
                continue
            if not entries: continue
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
                        "source": self._extract_source(link),
                        "published": pub_ts,
                        "summary": getattr(entry, 'summary', '')[:1000]
                    })
                except Exception:
                    continue
        
        # Sort by date desc
        articles.sort(key=lambda x: x["published"], reverse=True)
        return articles

    def _extract_source(self, link: str) -> str:
        if "decrypt.co" in link: return "Decrypt"
        if "coindesk.com" in link: return "CoinDesk"
        if "cointelegraph.com" in link: return "CoinTelegraph"
        if "cryptopanic.com" in link: return "CryptoPanic"
        if "theblock.co" in link: return "The Block"
        if "bitcoinmagazine.com" in link: return "Bitcoin Magazine"
        if "coinbase.com" in link: return "Coinbase Blog"
        if "binance.com" in link: return "Binance"
        if "messari.io" in link: return "Messari"
        if "coinglass.com" in link: return "Coinglass"
        if "newsbtc.com" in link: return "NewsBTC"
        if "cryptoslate.com" in link: return "CryptoSlate"
        if "u.today" in link: return "U.Today"
        return "News"

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

    def _sanitize_comment(self, text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"\s+", " ", text).strip()
        for p in self._toxic_patterns:
            if re.search(p, cleaned, flags=re.IGNORECASE):
                return "Risk is elevated. Avoid emotional decisions, reduce size, and wait for confirmation before acting."
        return cleaned[:900]

    async def fetch_news_with_search(self, timeframe: str = "24h", topics: list = None) -> str:
        """
        News Agent: Collects fresh crypto news via Google Search grounding.
        Returns: Structured news summary from Google Search
        """
        if topics is None:
            topics = ["Hyperliquid", "Bitcoin", "Ethereum", "crypto market"]

        topic_str = ", ".join(topics)

        prompt = f"""You are a News Agent. Search Google for the latest {timeframe} crypto news related to: {topic_str}.

Focus on:
- Major price movements and market events
- Important protocol updates or launches
- Regulatory news
- Institutional activity (ETFs, large purchases)
- Technical developments

Provide a concise summary (max 500 words) with key bullet points."""

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{
                "googleSearchRetrieval": {
                    "dynamicRetrievalConfig": {
                        "mode": "MODE_DYNAMIC",
                        "dynamicThreshold": 0.7
                    }
                }
            }],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 1024
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.news_agent_url, json=payload, timeout=25) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()

                        # Extract grounding metadata if available
                        grounding_meta = data.get("candidates", [{}])[0].get("groundingMetadata", {})
                        sources = grounding_meta.get("groundingChunks", [])

                        logger.info(f"News Agent found {len(sources)} sources")
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
        Hedge Agent: RAG system that combines market data + fresh news from News Agent.

        Flow:
        1. News Agent collects fresh crypto news via Google Search
        2. Hedge Agent analyzes market data + news and generates final response
        """
        target_lang = "Russian" if lang == "ru" else "English"

        # Step 1: Get fresh news from News Agent (with Google Search grounding)
        logger.info("News Agent: Fetching fresh crypto news...")
        topics = ["Hyperliquid", "Bitcoin", "Ethereum", "crypto market"]

        # Add top gainers/losers to search topics
        if market_data.get('top_gainers'):
            for g in market_data['top_gainers'][:2]:
                topics.append(g.get('name', ''))
        if market_data.get('top_losers'):
            for l in market_data['top_losers'][:2]:
                topics.append(l.get('name', ''))

        fresh_news = await self.fetch_news_with_search(timeframe="24h", topics=topics)
        rss_news = self._format_news_digest(news, limit=10)
        combined_news = f"RSS HEADLINES:\n{rss_news}\n\nSEARCH DIGEST:\n{fresh_news or 'No search digest'}"

        # Step 2: Hedge Agent analyzes everything
        logger.info("Hedge Agent: Analyzing market data + news...")
        prompt = f"""
        You are HEDGE AI, an institutional AI analyst with RAG capabilities.
        Analyze the current market state on Hyperliquid L1 using PROVIDED DATA.

        PERIOD: {period_name}
        LANGUAGE: {target_lang}
        STYLE: {style}
        {f"USER CUSTOM STYLE: {custom_prompt}" if custom_prompt else ""}

        MARKET DATA (Hyperliquid L1):
        - 24h Volume: ${market_data.get('global_volume', 'N/A')}
        - Total Open Interest: ${market_data.get('total_oi', 'N/A')}
        - Top Gainers: {', '.join([f"{g['name']} {g['change']}%" for g in market_data.get('top_gainers', [])[:3]])}
        - Top Losers: {', '.join([f"{l['name']} {l['change']}%" for l in market_data.get('top_losers', [])[:3]])}
        - ETF Flows: BTC ${market_data.get('etf_flows', {}).get('btc_flow', 0)}M, ETH ${market_data.get('etf_flows', {}).get('eth_flow', 0)}M

        NEWS INTELLIGENCE (Google Search + RSS):
        {combined_news}

        TASK:
        Synthesize market data + news into actionable intelligence.

        RESPONSE REQUIREMENTS:
        1. "summary": Sharp analysis connecting market movements to news events (max 500 chars). Use **bold** for key assets/events.
        2. "sentiment": One word (BULLISH, BEARISH, NEUTRAL, CAUTIOUS, EXPLOSIVE)
        3. "next_event": What traders should watch next (max 100 chars)
        4. Professional tone only. No insults, no taunting, no certainty claims like "guaranteed" or "safe".

        OUTPUT: Strictly JSON.
        """

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.4,
                "response_mime_type": "application/json"
            }
        }

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
                        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                        # Clean markdown if present
                        if "```json" in text:
                            text = text.split("```json")[1].split("```")[0].strip()

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
        from bot.services import get_user_portfolio, get_spot_balances, get_perps_state
        
        # 1. Fetch User Context
        wallets = await db.list_wallets(user_id)
        portfolio_summary = ""
        
        if wallets:
            # Parallel fetch for all wallets
            results = await asyncio.gather(*[
                asyncio.gather(get_spot_balances(w), get_perps_state(w), return_exceptions=True) 
                for w in wallets
            ])
            
            all_spot = []
            all_pos = []
            
            for spot, perps in results:
                if isinstance(spot, list):
                    for b in spot:
                        if float(b.get('total', 0)) > 0:
                            coin_id = b.get('coin')
                            from bot.services import get_symbol_name
                            name = await get_symbol_name(coin_id, is_spot=True)
                            all_spot.append(f"{name}={b.get('total')}")
                if isinstance(perps, dict) and perps.get('assetPositions'):
                    for p in perps['assetPositions']:
                        pos = p['position']
                        if float(pos.get('szi', 0)) != 0:
                            coin_id = pos.get('coin')
                            from bot.services import get_symbol_name
                            name = await get_symbol_name(coin_id, is_spot=False)
                            all_pos.append(f"{name} {pos.get('szi')}")
            
            portfolio_summary = f"Spot: {', '.join(all_spot[:10])} | Perps: {', '.join(all_pos[:10])}"
        if not portfolio_summary:
            portfolio_summary = "No portfolio data."

        watchlist = await db.get_watchlist(user_id)
        watchlist_str = ", ".join(watchlist)
        memory = await db.get_hedge_memory(user_id, limit=12)
        memory_txt = "\n".join(
            [f"- {m.get('role', 'system')}: {str(m.get('content', ''))[:220]}" for m in memory if m.get("content")]
        ) or "No prior context."

        # 2. Fetch Style (Prompt Override)
        ov_settings = await db.get_overview_settings(user_id)
        custom_style = ov_settings.get("prompt_override", "Professional and sharp.")
        
        # 3. Fetch Fresh News via News Agent
        event_symbol = event_data.get('symbol', event_data.get('sym', ''))
        topics = ["crypto market"]
        if event_symbol:
            topics.append(event_symbol)

        logger.info(f"Hedge Chat: Fetching news for context_type={context_type}")
        rss_news = await self.fetch_news_rss(since_timestamp=time.time() - 12 * 3600)
        fresh_news = await self.fetch_news_with_search(timeframe="12h", topics=topics)
        news_digest = self._format_news_digest(rss_news, limit=8)

        target_lang = "Russian" if lang == "ru" else "English"

        # 4. Construct RAG prompt
        prompt = f"""
        You are HEDGE AI, an elite AI risk manager with real-time news access.
        NON-NEGOTIABLE RULES:
        - Never insult, mock, humiliate, or use toxic language.
        - Never mention user's "poverty", "small balance", or similar.
        - Be factual and uncertainty-aware: avoid guaranteed predictions.
        - Keep output <= 320 characters for non-chat contexts.
        - If data is weak, say so briefly and give a conservative action.
        USER STYLE/PROMPT: {custom_style}
        TARGET LANGUAGE: {target_lang}

        USER CONTEXT:
        - Portfolio: {portfolio_summary}
        - Watchlist: {watchlist_str}

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
            prompt += f"\nCHAT HISTORY:\n{json.dumps(history if history else [])}\nACTION: Reply to the user's latest message considering all context. Be helpful, concise, and professional."
        else:
            prompt += f"\nACTION: Provide a very brief (max 300 chars), sharp, and actionable insight about this event. Connect it to the user's portfolio or current market news if possible."

        prompt += "\nOUTPUT: Plain text only, no JSON, no headers. Use Markdown **bolding** for emphasis."

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7}
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
