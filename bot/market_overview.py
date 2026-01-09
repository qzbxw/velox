import aiohttp
import asyncio
import logging
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
        # Prepare context
        news_text = "\n".join([f"- {n['title']} ({n['source']}): {n['summary'][:300]}..." for n in news[:20]])
        if not news_text: news_text = "No major news found."

        btc = market_data.get("BTC", {})
        eth = market_data.get("ETH", {})
        
        target_lang = "Russian" if lang == "ru" else "English"
        
        prompt = f"""
        You are VELOX AI, an elite crypto market intelligence system. Analyze the data and news for "{period_name}".
        
        MARKET DATA:
        - BTC: ${pretty_float(btc.get('price', 0))} ({btc.get('change_24h', 0):+.2f}%)
        - ETH: ${pretty_float(eth.get('price', 0))} ({eth.get('change_24h', 0):+.2f}%)
        - ETF Flows: BTC {market_data.get('btc_etf_flow', 0):+.1f}M, ETH {market_data.get('eth_etf_flow', 0):+.1f}M
        
        NEWS:
        {news_text}
        
        OUTPUT FORMAT (JSON ONLY):
        {{
            "summary": "A deep, analytical market report in {target_lang}. Target length: 2000-3000 characters. Style: Professional, sharp, institutional-grade but engaging. Use emojis sparingly. Structure with clear paragraphs. Focus on macro drivers, on-chain data implications, and sentiment shifts. Do NOT use Markdown headers (like # or ##), use bolding for emphasis.",
            "sentiment": "Bullish/Bearish/Neutral",
            "next_event": "Key upcoming event (e.g. FOMC, CPI) in {target_lang}. Max 30 chars."
        }}
        """
        
        if custom_prompt:
            prompt += f"\n\nUSER NOTE: {custom_prompt}"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "responseMimeType": "application/json"
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.gemini_url, json=payload, timeout=20) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        text = data["candidates"][0]["content"]["parts"][0]["text"]
                        import json
                        return json.loads(text)
                    else:
                        logger.error(f"Gemini API Error: {resp.status} - {await resp.text()}")
                        return {
                            "summary": "⚠️ Failed to generate summary.", 
                            "sentiment": "Neutral", 
                            "next_event": "N/A"
                        }
        except Exception as e:
            logger.error(f"Gemini Request Failed: {e}")
            return {
                "summary": "⚠️ Failed to generate summary.", 
                "sentiment": "Neutral", 
                "next_event": "N/A"
            }

market_overview = MarketOverview()
