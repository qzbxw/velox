import asyncio
import datetime
from io import BytesIO

import bot.scheduler as scheduler
from bot.agent.context import FinalAgentReport, MarketSnapshot


def test_send_scheduled_overviews_uses_agent_when_enabled(monkeypatch):
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M")
    called = {}

    async def fake_get_all_users():
        return [{"user_id": 123, "lang": "en"}]

    async def fake_get_overview_settings(user_id):
        return {
            "enabled": True,
            "schedules": [now_utc],
            "prompt_override": "Focus on risk.",
            "style": "brief",
        }

    async def fake_get_perps_context():
        return {
            "universe": [{"name": "BTC"}, {"name": "ETH"}],
            "assetCtxs": [
                {"markPx": "100000", "prevDayPx": "99000"},
                {"markPx": "3000", "prevDayPx": "3100"},
            ],
        }

    async def fake_fetch_etf_flows():
        return {"btc_flow": 0, "eth_flow": 0}

    async def fake_fear_greed():
        return {"value": 50, "classification": "Neutral"}

    async def fake_generate_agentic_overview(**kwargs):
        called.update(kwargs)
        return FinalAgentReport(
            run_id="run-1",
            mode="overview",
            output={
                "summary": "Agent summary",
                "sentiment": "NEUTRAL",
                "actionable_notes": ["Check leverage."],
            },
            market_snapshot=MarketSnapshot(
                majors={
                    "BTC": {"price": 100000, "change": 1.0},
                    "ETH": {"price": 3000, "change": -1.0},
                },
                top_gainers=[{"name": "BTC", "change": 1.0}],
                top_losers=[{"name": "ETH", "change": -1.0}],
                highest_volume=[{"name": "BTC", "volume": 100_000_000}],
                highest_funding=[{"name": "ETH", "funding": 0.0001}],
                fear_greed={"value": 50, "classification": "Neutral"},
            ),
        )

    async def fake_render_html_to_image(*args, **kwargs):
        return BytesIO(b"png")

    class FakeBot:
        def __init__(self):
            self.photos = []
            self.messages = []

        async def send_photo(self, *args, **kwargs):
            self.photos.append((args, kwargs))

        async def send_message(self, *args, **kwargs):
            self.messages.append((args, kwargs))

    monkeypatch.setattr(scheduler.settings, "AGENT_ENABLED", True, raising=False)
    monkeypatch.setattr(scheduler.db, "get_all_users", fake_get_all_users)
    monkeypatch.setattr(scheduler.db, "get_overview_settings", fake_get_overview_settings)
    monkeypatch.setattr(scheduler, "get_perps_context", fake_get_perps_context)
    monkeypatch.setattr(scheduler.rss_engine, "get_cached_articles", lambda limit=200: [])
    monkeypatch.setattr(scheduler.market_overview, "fetch_etf_flows", fake_fetch_etf_flows)
    monkeypatch.setattr(scheduler, "get_fear_greed_index", fake_fear_greed)
    monkeypatch.setattr(scheduler.market_overview, "generate_agentic_overview", fake_generate_agentic_overview)
    monkeypatch.setattr(scheduler, "render_html_to_image", fake_render_html_to_image)

    bot = FakeBot()
    asyncio.run(scheduler.send_scheduled_overviews(bot))

    assert called["user_id"] == 123
    assert called["custom_prompt"] == "Focus on risk."
    assert called["style"] == "brief"
    assert bot.photos
    assert bot.messages
