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
        self.gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={settings.GEMINI_API_KEY}"
        self.rss_feeds = [
            "https://decrypt.co/feed",
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            "https://cointelegraph.com/rss",
            "https://cryptopanic.com/news/rss/" 
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
        except:
            return None

    async def fetch_news_rss(self, since_timestamp: float = 0) -> list[dict]:
        """
        Fetches news from RSS feeds published after since_timestamp.
        """
        articles = []
        
        async def fetch_feed(url):
            try:
                async with aiohttp.ClientSession() as session:
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

        results = await asyncio.gather(*[fetch_feed(url) for url in self.rss_feeds])
        
        seen_links = set()

        for entries in results:
            if not entries: continue
            for entry in entries:
                # Deduplicate by link
                if entry.link in seen_links: continue
                seen_links.add(entry.link)

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
                        "title": entry.title,
                        "link": entry.link,
                        "source": self._extract_source(entry.link),
                        "published": pub_ts,
                        "summary": getattr(entry, 'summary', '')[:1000]
                    })
                except Exception as e:
                    continue
        
        # Sort by date desc
        articles.sort(key=lambda x: x["published"], reverse=True)
        return articles

    def _extract_source(self, link: str) -> str:
        if "decrypt.co" in link: return "Decrypt"
        if "coindesk.com" in link: return "CoinDesk"
        if "cointelegraph.com" in link: return "CoinTelegraph"
        if "cryptopanic.com" in link: return "CryptoPanic"
        return "News"

    async def generate_summary(self, 
                             market_data: dict, 
                             news: list[dict], 
                             period_name: str, 
                             custom_prompt: str | None = None,
                             style: str = "detailed",
                             lang: str = "en") -> dict:
        """
        Generates AI summary using Gemini in JSON format.
        Returns: {
            "summary": str,
            "sentiment": str,
            "next_event": str
        }
        """
        # ... (rest of the method)
        return # existing code placeholder for structure

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

        watchlist = await db.get_watchlist(user_id)
        watchlist_str = ", ".join(watchlist)

        # 2. Fetch Style (Prompt Override)
        ov_settings = await db.get_overview_settings(user_id)
        custom_style = ov_settings.get("prompt_override", "Professional and sharp.")
        
        # 3. Fetch Market Context (Recent News)
        news = await self.fetch_news_rss(since_timestamp=time.time() - 43200) # 12h
        news_text = "\n".join([f"- {n['title']}" for n in news[:5]])

        target_lang = "Russian" if lang == "ru" else "English"
        
        # 4. Construct specialized prompt
        prompt = f"""
        You are VELOX HEDGE, an elite AI risk manager.
        USER STYLE/PROMPT: {custom_style}
        TARGET LANGUAGE: {target_lang}
        
        USER CONTEXT:
        - Portfolio: {portfolio_summary}
        - Watchlist: {watchlist_str}
        
        MARKET CONTEXT:
        {news_text}
        
        EVENT TYPE: {context_type.upper()}
        EVENT DATA: {json.dumps(event_data)}
        """
        
        if context_type == 'chat':
            prompt += f"\nCHAT HISTORY:\n{json.dumps(history if history else [])}\nACTION: Reply to the user's latest message considering all context. Be helpful, concise, and professional."
        else:
            prompt += f"\nACTION: Provide a very brief (max 300 chars), sharp, and actionable insight about this event. Connect it to the user's portfolio or current market news if possible."

        prompt += "\nOUTPUT: Plain text only, no JSON, no headers. Use HTML bolding <b>text</b> for emphasis."

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7}
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.gemini_url, json=payload, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except:
            pass
        return ""

market_overview = MarketOverview()
