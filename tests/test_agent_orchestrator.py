import asyncio

from bot.agent.context import AgentRunContext, MarketEvent, MarketRegime, MarketSnapshot, SourceItem
from bot.agent.orchestrator import AgentOrchestrator
from bot.agent.processors.risk_synthesizer import deterministic_report, normalize_report_output, synthesize_final_report
from bot.agent.registry import ToolRegistry
from bot.agent.tools.base import BaseAgentTool, ToolResult


class GoodTool(BaseAgentTool):
    name = "good"

    async def collect(self, context, queries=None):
        return ToolResult(self.name, [
            SourceItem("BTC ETF inflows lift market", "https://coindesk.com/a", "CoinDesk", "rss", "BTC ETF inflows")
        ])


class FailingTool(BaseAgentTool):
    name = "failing"

    async def collect(self, context, queries=None):
        raise RuntimeError("boom")


class FakeExtractor:
    async def extract(self, context, sources):
        return [MarketEvent(title="BTC ETF inflows lift market", category="institutional", assets=["BTC"], sentiment="bullish")]


class NoopRunStore:
    async def save(self, *args, **kwargs):
        return None


class NoopEventStore:
    async def upsert_many(self, events):
        return None


class NoopSourceCache:
    async def put_many(self, *args, **kwargs):
        return None


def test_orchestrator_run_completes_and_tolerates_failing_tool(monkeypatch):
    registry = ToolRegistry()
    registry.register(GoodTool())
    registry.register(FailingTool())
    orch = AgentOrchestrator(
        registry=registry,
        event_extractor=FakeExtractor(),
        run_store=NoopRunStore(),
        event_store=NoopEventStore(),
        source_cache=NoopSourceCache(),
    )

    async def fake_snapshot(context):
        return MarketSnapshot(
            global_volume=100,
            total_oi=50,
            majors={"BTC": {"name": "BTC", "price": 100000, "change": 2.0}},
            top_gainers=[{"name": "BTC", "change": 2.0}],
            top_losers=[{"name": "ETH", "change": -1.0}],
            highest_volume=[{"name": "BTC", "volume": 100}],
            highest_funding=[{"name": "BTC", "funding": 0.0001}],
        )

    async def fake_exposure(user_id):
        from bot.agent.context import PortfolioExposure
        return PortfolioExposure()

    monkeypatch.setattr(orch, "collect_market_snapshot", fake_snapshot)
    monkeypatch.setattr("bot.agent.orchestrator.build_portfolio_exposure", fake_exposure)

    report = asyncio.run(orch.run(mode="overview", lang="en"))
    assert report.run_id
    assert report.output["summary"]
    assert len(report.sources) == 1
    assert len(report.events) == 1
    assert any(err["tool"] == "failing" for err in report.errors)


def test_orchestrator_propagates_generation_settings(monkeypatch):
    registry = ToolRegistry()
    registry.register(GoodTool())
    orch = AgentOrchestrator(
        registry=registry,
        event_extractor=FakeExtractor(),
        run_store=NoopRunStore(),
        event_store=NoopEventStore(),
        source_cache=NoopSourceCache(),
    )
    captured = {}

    async def fake_snapshot(context):
        return MarketSnapshot()

    async def fake_exposure(user_id):
        from bot.agent.context import PortfolioExposure
        return PortfolioExposure()

    async def fake_synthesize(context, snapshot, regime, events, relevance, sources):
        captured["custom_prompt"] = context.custom_prompt
        captured["style"] = context.style
        return {
            "summary": "ok",
            "sentiment": "NEUTRAL",
            "regime": "neutral",
            "top_risks": [],
            "top_opportunities": [],
            "portfolio_relevance": [],
            "next_event": "none",
            "actionable_notes": [],
            "sources": [],
        }

    monkeypatch.setattr(orch, "collect_market_snapshot", fake_snapshot)
    monkeypatch.setattr("bot.agent.orchestrator.build_portfolio_exposure", fake_exposure)
    monkeypatch.setattr("bot.agent.orchestrator.synthesize_final_report", fake_synthesize)

    asyncio.run(
        orch.run(
            mode="overview",
            lang="en",
            custom_prompt="Focus on ETF flow risk.",
            style="brief",
        )
    )

    assert captured == {
        "custom_prompt": "Focus on ETF flow risk.",
        "style": "brief",
    }


def test_synthesizer_includes_generation_settings_in_prompt(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200

        async def json(self):
            return {
                "candidates": [{
                    "content": {
                        "parts": [{
                            "text": """{
                                "summary": "ok",
                                "sentiment": "NEUTRAL",
                                "regime": "neutral",
                                "top_risks": [],
                                "top_opportunities": [],
                                "portfolio_relevance": [],
                                "next_event": "none",
                                "actionable_notes": [],
                                "sources": []
                            }"""
                        }]
                    }
                }]
            }

    class FakePost:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeSession:
        def post(self, url, json, timeout):
            captured["prompt"] = json["contents"][0]["parts"][0]["text"]
            return FakePost()

    async def fake_get_session():
        return FakeSession()

    monkeypatch.setattr("bot.agent.processors.risk_synthesizer.settings.GEMINI_API_KEY", "test-key", raising=False)
    monkeypatch.setattr("bot.agent.processors.risk_synthesizer.get_session", fake_get_session)

    context = AgentRunContext(
        custom_prompt="Focus on ETF flow risk.",
        style="brief",
    )
    asyncio.run(
        synthesize_final_report(
            context,
            MarketSnapshot(),
            MarketRegime(),
            [],
            [],
            [],
        )
    )

    assert "Generation style: brief." in captured["prompt"]
    assert "User generation instructions: Focus on ETF flow risk." in captured["prompt"]


def test_deterministic_report_synthesizes_instead_of_dumping_raw_links():
    report = deterministic_report(
        MarketSnapshot(),
        MarketRegime(regime="transitional", summary="Transitional regime with score 1.74."),
        [
            MarketEvent(
                title="ETH ETF flows flip late",
                summary="<a href=\"https://news.google.com/rss/articles/raw\">Ethereum source</a>",
                sentiment="bullish",
            )
        ],
        [],
        [
            SourceItem(
                title="Ethereum (ETH) Holds $2.3K as ETF Flows Flip Late",
                url="https://news.google.com/rss/articles/raw?oc=5",
                source="Google News",
                source_type="rss",
            )
        ],
    )

    assert "score 1.74" not in report["summary"]
    assert "<a href" not in report["summary"]
    assert "https://news.google.com" not in report["summary"]
    assert "Market regime is transitional" in report["summary"]
    assert report["sources"][0]["url"] == "https://news.google.com/rss/articles/raw?oc=5"


def test_normalize_report_output_removes_links_from_text_fields_only():
    output = normalize_report_output({
        "summary": "Key event: <a href=\"https://example.com/a\">ETH flow flip</a>",
        "sentiment": "neutral",
        "regime": "transitional",
        "top_risks": ["Raw https://example.com/risk"],
        "top_opportunities": ["[ETF demand](https://example.com/opp)"],
        "portfolio_relevance": [],
        "next_event": "Watch https://example.com/event",
        "actionable_notes": ["Check <b>funding</b>"],
        "sources": [{"title": "Source <b>title</b>", "url": "https://example.com/a", "source": "Example"}],
    })

    assert output["summary"] == "Key event: ETH flow flip"
    assert output["top_risks"] == ["Raw"]
    assert output["top_opportunities"] == ["ETF demand"]
    assert output["next_event"] == "Watch"
    assert output["actionable_notes"] == ["Check funding"]
    assert output["sources"] == [{"title": "Source title", "url": "https://example.com/a", "source": "Example"}]
