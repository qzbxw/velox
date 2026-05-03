from bot.agent.context import MarketEvent
from bot.agent.processors.event_extractor import parse_events_json


def test_valid_market_event_json_accepted():
    events = parse_events_json("""[
      {"title":"SEC approves crypto rule","category":"regulatory","assets":["BTC"],"sentiment":"bullish","impact":"high","confidence":0.8}
    ]""")
    assert len(events) == 1
    assert events[0].category == "regulatory"
    assert events[0].event_id


def test_invalid_category_sentiment_impact_handled():
    event = MarketEvent.from_dict({
        "title": "Unknown rumor",
        "category": "nonsense",
        "sentiment": "moon",
        "impact": "huge",
    })
    assert event.category == "other"
    assert event.sentiment == "neutral"
    assert event.impact == "medium"
