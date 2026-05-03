from __future__ import annotations

import time
from email.utils import parsedate_to_datetime
from typing import Any

from bot.agent.context import AgentRunContext, SourceItem
from bot.agent.tools.base import BaseAgentTool, ToolResult
from bot.rss_engine import rss_engine


def _article_published_ts(article: dict[str, Any]) -> float | None:
    value = article.get("published_ts") or article.get("ts") or article.get("published")
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) or None
    if isinstance(value, str):
        try:
            return float(value) or None
        except ValueError:
            pass
        try:
            parsed = parsedate_to_datetime(value)
            return parsed.timestamp() if parsed else None
        except (TypeError, ValueError, OverflowError):
            return None
    return None


class RSSTool(BaseAgentTool):
    name = "rss"
    source_type = "rss"

    async def collect(self, context: AgentRunContext, queries: list[str] | None = None) -> ToolResult:
        articles = rss_engine.get_cached_articles(limit=context.max_sources)
        if not articles:
            articles = await rss_engine.fetch_all(since_hours=24)
        sources = []
        for article in articles[: context.max_sources]:
            sources.append(SourceItem(
                title=str(article.get("title") or ""),
                url=str(article.get("link") or article.get("url") or ""),
                source=str(article.get("source") or article.get("feed") or "RSS"),
                source_type=self.source_type,
                snippet=str(article.get("summary") or article.get("description") or ""),
                content=str(article.get("content") or ""),
                published_ts=_article_published_ts(article),
                fetched_ts=time.time(),
                metadata={"category": article.get("category")},
                raw=article,
            ))
        return ToolResult(self.name, [s for s in sources if s.title or s.url])
