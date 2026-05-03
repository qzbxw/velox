from __future__ import annotations

from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from bot.agent.context import AgentRunContext, SourceItem
from bot.agent.tools.base import BaseAgentTool, ToolResult
from bot.config import settings
from bot.services import get_session


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_brave_results(html: str, query: str = "") -> list[SourceItem]:
    soup = BeautifulSoup(html or "", "html.parser")
    cards = soup.select(".snippet, .web-result, [data-type='web']")
    if not cards:
        cards = soup.select("div:has(a[href^='http'])")
    results: list[SourceItem] = []
    for card in cards:
        link = card.select_one("a[href^='http']")
        if not link:
            continue
        url = link.get("href", "")
        title = link.get_text(" ", strip=True)
        snippet_node = card.select_one(".snippet-description, .description, .snippet-content, p")
        snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
        if title and url.startswith("http"):
            results.append(SourceItem(title=title, url=url, source="Brave Search", source_type="search", snippet=snippet, metadata={"query": query}))
    return results[:10]


class BraveSearchTool(BaseAgentTool):
    name = "brave_search"
    source_type = "search"

    def enabled(self, context: AgentRunContext) -> bool:
        return bool(getattr(settings, "AGENT_SEARCH_ENABLED", True) and getattr(settings, "AGENT_BRAVE_SEARCH_ENABLED", True))

    async def collect(self, context: AgentRunContext, queries: list[str] | None = None) -> ToolResult:
        session = await get_session()
        sources: list[SourceItem] = []
        errors: list[str] = []
        for query in (queries or [])[: context.max_queries]:
            url = f"https://search.brave.com/search?q={quote_plus(query)}"
            try:
                async with session.get(url, headers=HEADERS, timeout=getattr(settings, "AGENT_TOOL_TIMEOUT_SEC", 15)) as resp:
                    if resp.status in {403, 429}:
                        errors.append(f"{query}: blocked {resp.status}")
                        continue
                    if resp.status != 200:
                        errors.append(f"{query}: status {resp.status}")
                        continue
                    sources.extend(parse_brave_results(await resp.text(), query=query))
            except Exception as exc:
                errors.append(f"{query}: {exc}")
        return ToolResult(self.name, sources, errors)
