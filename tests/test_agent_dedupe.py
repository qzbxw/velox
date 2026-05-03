from bot.agent.context import SourceItem
from bot.agent.processors.dedupe import canonical_url, dedupe_sources


def test_duplicate_canonical_urls_collapse():
    items = [
        SourceItem("BTC ETF flows", "https://www.example.com/a?utm_source=x", "A", "rss"),
        SourceItem("BTC ETF flows update", "https://example.com/a", "B", "rss"),
    ]
    result = dedupe_sources(items)
    assert len(result) == 1
    assert canonical_url(result[0].url) == "https://example.com/a"


def test_same_normalized_title_collapses():
    items = [
        SourceItem("Bitcoin ETF Flows!", "https://a.test/1", "A", "rss"),
        SourceItem("bitcoin etf flows", "https://b.test/2", "B", "rss"),
    ]
    assert len(dedupe_sources(items)) == 1


def test_near_identical_titles_collapse():
    items = [
        SourceItem("Hyperliquid volume rises as traders add risk", "https://a.test/1", "A", "rss"),
        SourceItem("Hyperliquid volume rises as traders add risks", "https://b.test/2", "B", "rss"),
    ]
    assert len(dedupe_sources(items)) == 1
