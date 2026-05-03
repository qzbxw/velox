import asyncio

from bot.agent.context import AgentRunContext
from bot.agent.tools.rss_tool import RSSTool


def test_rss_tool_uses_published_for_source_timestamp(monkeypatch):
    monkeypatch.setattr(
        "bot.agent.tools.rss_tool.rss_engine.get_cached_articles",
        lambda limit: [{
            "title": "BTC ETF flows rise",
            "link": "https://example.com/btc",
            "source": "Example",
            "summary": "Flows improved.",
            "published": 1_700_000_000,
        }],
    )

    result = asyncio.run(RSSTool().collect(AgentRunContext(max_sources=10)))

    assert result.sources[0].published_ts == 1_700_000_000.0
