import asyncio

from bot.agent.context import MarketEvent, MarketSnapshot, SourceItem
from bot.agent.orchestrator import AgentOrchestrator
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
