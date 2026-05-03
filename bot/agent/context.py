from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any


def _now() -> float:
    return time.time()


def to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return {k: to_plain(v) for k, v in asdict(value).items()}
    if isinstance(value, list):
        return [to_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: to_plain(v) for k, v in value.items()}
    return value


@dataclass
class SourceItem:
    title: str
    url: str
    source: str
    source_type: str
    snippet: str = ""
    content: str = ""
    published_ts: float | None = None
    fetched_ts: float = field(default_factory=_now)
    assets: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: Any = None


@dataclass
class SourceScore:
    recency_score: float
    source_reputation_score: float
    market_relevance_score: float
    cross_source_confirmation_score: float
    final_score: float
    reasons: list[str] = field(default_factory=list)


@dataclass
class MarketSnapshot:
    global_volume: float = 0.0
    total_oi: float = 0.0
    top_gainers: list[dict[str, Any]] = field(default_factory=list)
    top_losers: list[dict[str, Any]] = field(default_factory=list)
    highest_funding: list[dict[str, Any]] = field(default_factory=list)
    highest_volume: list[dict[str, Any]] = field(default_factory=list)
    majors: dict[str, dict[str, Any]] = field(default_factory=dict)
    fear_greed: dict[str, Any] = field(default_factory=dict)
    etf_flows: dict[str, Any] = field(default_factory=dict)
    defillama: dict[str, Any] = field(default_factory=dict)
    coingecko: dict[str, Any] = field(default_factory=dict)


EVENT_CATEGORIES = {
    "macro", "regulatory", "institutional", "onchain", "derivatives",
    "protocol", "security", "market_structure", "asset_specific", "other"
}
EVENT_SENTIMENTS = {"bullish", "bearish", "neutral", "mixed"}
EVENT_IMPACTS = {"low", "medium", "high", "critical"}


@dataclass
class MarketEvent:
    title: str
    category: str = "other"
    assets: list[str] = field(default_factory=list)
    summary: str = ""
    sentiment: str = "neutral"
    impact: str = "medium"
    confidence: float = 0.5
    source_urls: list[str] = field(default_factory=list)
    published_ts: float | None = None
    event_id: str = ""

    def __post_init__(self) -> None:
        self.category = self.category if self.category in EVENT_CATEGORIES else "other"
        self.sentiment = self.sentiment if self.sentiment in EVENT_SENTIMENTS else "neutral"
        self.impact = self.impact if self.impact in EVENT_IMPACTS else "medium"
        self.assets = [str(a).upper() for a in self.assets if a]
        self.confidence = max(0.0, min(1.0, float(self.confidence or 0.5)))
        if not self.event_id:
            seed = "|".join([
                self.title.strip().lower(),
                self.category,
                ",".join(sorted(self.assets)),
            ])
            self.event_id = hashlib.sha1(seed.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MarketEvent":
        return cls(
            title=str(data.get("title") or data.get("headline") or "Market event"),
            category=str(data.get("category") or "other").lower(),
            assets=data.get("assets") if isinstance(data.get("assets"), list) else [],
            summary=str(data.get("summary") or data.get("description") or ""),
            sentiment=str(data.get("sentiment") or "neutral").lower(),
            impact=str(data.get("impact") or "medium").lower(),
            confidence=float(data.get("confidence", 0.5) or 0.5),
            source_urls=data.get("source_urls") if isinstance(data.get("source_urls"), list) else [],
            published_ts=data.get("published_ts"),
            event_id=str(data.get("event_id") or ""),
        )


@dataclass
class MarketRegime:
    regime: str = "neutral"
    confidence: float = 0.5
    summary: str = "Market regime is mixed."
    main_drivers: list[str] = field(default_factory=list)


@dataclass
class PortfolioExposure:
    wallets: list[str] = field(default_factory=list)
    spot_balances: list[dict[str, Any]] = field(default_factory=list)
    perps_positions: list[dict[str, Any]] = field(default_factory=list)
    watchlist: list[str] = field(default_factory=list)


@dataclass
class PortfolioRelevantEvent:
    event: MarketEvent
    relevance_score: float
    exposure_type: str
    matched_symbols: list[str]
    reason: str
    suggested_risk_focus: str


@dataclass
class FinalAgentReport:
    run_id: str
    mode: str
    output: dict[str, Any]
    market_snapshot: MarketSnapshot = field(default_factory=MarketSnapshot)
    market_regime: MarketRegime = field(default_factory=MarketRegime)
    events: list[MarketEvent] = field(default_factory=list)
    sources: list[SourceItem] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    used_tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass
class AgentRunContext:
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: float = field(default_factory=_now)
    mode: str = "overview"
    user_id: int | str | None = None
    event_data: dict[str, Any] | None = None
    lang: str = "en"
    custom_prompt: str | None = None
    style: str = "detailed"
    max_sources: int = 80
    max_queries: int = 12
    errors: list[dict[str, Any]] = field(default_factory=list)
    used_tools: list[str] = field(default_factory=list)

    def add_error(self, stage: str, error: Exception | str, tool: str | None = None) -> None:
        self.errors.append({
            "stage": stage,
            "tool": tool,
            "message": str(error),
            "ts": _now(),
        })
