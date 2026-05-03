from __future__ import annotations

import calendar
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import feedparser

from bot.agent.context import AgentRunContext, SourceItem
from bot.agent.tools.base import BaseAgentTool, ToolResult
from bot.config import settings
from bot.services import get_session


class GoogleNewsRSSTool(BaseAgentTool):
    name = "google_news_rss"
    source_type = "google_news_rss"

    def enabled(self, context: AgentRunContext) -> bool:
        return bool(getattr(settings, "AGENT_SEARCH_ENABLED", True))

    async def collect(self, context: AgentRunContext, queries: list[str] | None = None) -> ToolResult:
        session = await get_session()
        sources: list[SourceItem] = []
        errors: list[str] = []
        for query in (queries or [])[: context.max_queries]:
            url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
            try:
                async with session.get(url, timeout=getattr(settings, "AGENT_TOOL_TIMEOUT_SEC", 15)) as resp:
                    if resp.status != 200:
                        errors.append(f"{query}: status {resp.status}")
                        continue
                    parsed = feedparser.parse(await resp.text())
                    for entry in parsed.entries[:8]:
                        published_ts = None
                        if getattr(entry, "published", None):
                            try:
                                published_ts = calendar.timegm(parsedate_to_datetime(entry.published).utctimetuple())
                            except Exception:
                                published_ts = None
                        sources.append(SourceItem(
                            title=str(getattr(entry, "title", "")),
                            url=str(getattr(entry, "link", "")),
                            source="Google News",
                            source_type=self.source_type,
                            snippet=str(getattr(entry, "summary", "")),
                            published_ts=published_ts,
                            metadata={"query": query},
                            raw=dict(entry),
                        ))
            except Exception as exc:
                errors.append(f"{query}: {exc}")
        return ToolResult(self.name, sources, errors)
