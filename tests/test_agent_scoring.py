import time

from bot.agent.context import SourceItem
from bot.agent.processors.credibility import score_sources


def test_fresh_tier_one_source_scores_higher_than_old_noisy_source():
    fresh = SourceItem(
        "Bitcoin ETF inflows lift crypto market",
        "https://coindesk.com/markets/btc-etf",
        "CoinDesk",
        "rss",
        published_ts=time.time() - 600,
    )
    old = SourceItem(
        "Random crypto rumor",
        "https://reddit.com/r/crypto/post",
        "Reddit",
        "search",
        published_ts=time.time() - 7 * 86400,
    )
    scored = score_sources([old, fresh])
    assert scored[0][0] is fresh
    assert scored[0][1].final_score > scored[1][1].final_score


def test_asset_keyword_relevance_raises_market_relevance():
    asset = SourceItem("SOL funding and open interest jump", "https://x.test/a", "X", "rss")
    generic = SourceItem("Company announces new office", "https://x.test/b", "X", "rss")
    scores = {item.title: score for item, score in score_sources([asset, generic])}
    assert scores[asset.title].market_relevance_score > scores[generic.title].market_relevance_score


def test_repeated_topic_across_sources_raises_confirmation():
    one = SourceItem("BTC ETF inflows continue", "https://a.test/1", "A", "rss")
    two = SourceItem("Bitcoin ETF flows hit new high", "https://b.test/2", "B", "rss")
    scored = score_sources([one, two])
    assert any(score.cross_source_confirmation_score > 0 for _item, score in scored)
