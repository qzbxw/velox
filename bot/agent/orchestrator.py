from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

from bot.agent.config import pipeline_timeout
from bot.agent.context import AgentRunContext, FinalAgentReport, MarketSnapshot
from bot.agent.memory.event_store import EventStore
from bot.agent.memory.run_store import RunStore
from bot.agent.memory.source_cache import SourceCache
from bot.agent.processors.credibility import score_sources
from bot.agent.processors.dedupe import dedupe_sources
from bot.agent.processors.event_extractor import EventExtractor
from bot.agent.processors.market_regime import classify_market_regime
from bot.agent.processors.relevance_mapper import build_portfolio_exposure, map_portfolio_relevance
from bot.agent.processors.risk_synthesizer import synthesize_final_report
from bot.agent.registry import ToolRegistry
from bot.agent.tools.brave_search_tool import BraveSearchTool
from bot.agent.tools.duckduckgo_search_tool import DuckDuckGoSearchTool
from bot.agent.tools.farside_tool import FarsideTool
from bot.agent.tools.fear_greed_tool import FearGreedTool
from bot.agent.tools.google_news_rss_tool import GoogleNewsRSSTool
from bot.agent.tools.hyperliquid_tool import HyperliquidTool
from bot.agent.tools.rss_tool import RSSTool
from bot.config import settings

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    def __init__(
        self,
        registry: ToolRegistry | None = None,
        event_extractor: EventExtractor | None = None,
        run_store: RunStore | None = None,
        event_store: EventStore | None = None,
        source_cache: SourceCache | None = None,
    ) -> None:
        self.registry = registry or self._default_registry()
        self.event_extractor = event_extractor or EventExtractor()
        self.run_store = run_store or RunStore()
        self.event_store = event_store or EventStore()
        self.source_cache = source_cache or SourceCache()
        self.hyperliquid = HyperliquidTool()
        self.farside = FarsideTool()
        self.fear_greed = FearGreedTool()

    def _default_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(RSSTool())
        registry.register(GoogleNewsRSSTool())
        registry.register(BraveSearchTool())
        registry.register(DuckDuckGoSearchTool())
        return registry

    async def run(self, mode: str, user_id=None, event_data: dict[str, Any] | None = None, lang: str = "en") -> FinalAgentReport:
        return await asyncio.wait_for(self._run(mode, user_id=user_id, event_data=event_data, lang=lang), timeout=pipeline_timeout())

    async def _run(self, mode: str, user_id=None, event_data: dict[str, Any] | None = None, lang: str = "en") -> FinalAgentReport:
        context = AgentRunContext(
            mode=mode,
            user_id=user_id,
            event_data=event_data,
            lang=lang,
            max_sources=int(getattr(settings, "AGENT_MAX_SOURCES_PER_RUN", 80) or 80),
            max_queries=int(getattr(settings, "AGENT_MAX_SEARCH_QUERIES", 12) or 12),
        )
        snapshot = await self.collect_market_snapshot(context)
        queries = self.plan_search_queries(context, snapshot)
        raw_sources = await self.registry.run_collectors(context, queries)
        sources = dedupe_sources(raw_sources)
        scored = score_sources(sources)
        top_sources = [item for item, _score in scored[: context.max_sources]]
        events = await self.event_extractor.extract(context, top_sources)
        regime = classify_market_regime(snapshot, events)
        exposure = await build_portfolio_exposure(user_id)
        relevance = map_portfolio_relevance(events, exposure)
        output = await synthesize_final_report(context, snapshot, regime, events, relevance, top_sources)
        report = FinalAgentReport(
            run_id=context.run_id,
            mode=mode,
            output=output,
            market_snapshot=snapshot,
            market_regime=regime,
            events=events,
            sources=top_sources,
            errors=context.errors,
            used_tools=context.used_tools,
        )
        await self.persist(context, report)
        return report

    async def collect_market_snapshot(self, context: AgentRunContext) -> MarketSnapshot:
        snapshot = MarketSnapshot()
        results = await asyncio.gather(
            self.hyperliquid.collect_snapshot(),
            self.fear_greed.collect(),
            self.farside.collect(),
            return_exceptions=True,
        )
        if isinstance(results[0], MarketSnapshot):
            snapshot = results[0]
        else:
            context.add_error("collect_market_snapshot", results[0], tool="hyperliquid")
        if isinstance(results[1], dict):
            snapshot.fear_greed = results[1]
        else:
            context.add_error("collect_market_snapshot", results[1], tool="fear_greed")
        if isinstance(results[2], dict):
            snapshot.etf_flows = results[2]
        else:
            context.add_error("collect_market_snapshot", results[2], tool="farside")
        return snapshot

    def plan_search_queries(self, context: AgentRunContext, snapshot: MarketSnapshot) -> list[str]:
        if context.mode == "hedge_event" and context.event_data:
            symbol = str(context.event_data.get("symbol") or context.event_data.get("sym") or "").upper()
            queries = [
                f"{symbol} crypto news today",
                f"{symbol} price action",
                f"{symbol} funding open interest",
                f"Hyperliquid {symbol}",
            ] if symbol else ["crypto market news today"]
        else:
            queries = [
                "Hyperliquid latest news",
                "Bitcoin ETF flows today",
                "Ethereum ETF flows today",
                "Federal Reserve crypto market",
                "crypto regulation SEC CFTC",
            ]
            for row in (snapshot.top_gainers[:2] + snapshot.top_losers[:2]):
                if row.get("name"):
                    queries.append(f"{row['name']} crypto news today")
        return queries[: context.max_queries]

    async def persist(self, context: AgentRunContext, report: FinalAgentReport) -> None:
        input_hash = hashlib.sha1(json.dumps({
            "mode": context.mode,
            "user_id": context.user_id,
            "event_data": context.event_data,
        }, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        try:
            cache_tasks = []
            by_tool: dict[str, list] = {}
            for source in report.sources:
                by_tool.setdefault(source.source_type or "unknown", []).append(source)
            for tool_name, sources in by_tool.items():
                cache_tasks.append(self.source_cache.put_many(tool_name, sources[:20]))
            await asyncio.gather(
                self.run_store.save(report, user_id=context.user_id, started_at=context.started_at, input_hash=input_hash),
                self.event_store.upsert_many(report.events),
                *cache_tasks,
            )
        except Exception as exc:
            logger.debug("Agent persistence failed", exc_info=True)
            context.add_error("persist_agent_run", exc)


async def refresh_agent_sources(mode: str = "overview", lang: str = "en") -> FinalAgentReport:
    return await AgentOrchestrator().run(mode=mode, lang=lang)
